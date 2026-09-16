"""Validate release versions and built assets without importing Blender."""

import argparse
import ast
import hashlib
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing {name} in {path}")


def check_version(root=ROOT, tag=None):
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Releases currently require a stable X.Y.Z version")
    if assignment(root / "src/better_blender_mcp/__init__.py", "__version__") != version:
        raise ValueError("MCP version does not match pyproject.toml")
    addon = assignment(root / "blender_addon/better_blender_bridge/__init__.py", "bl_info")
    if ".".join(map(str, addon["version"])) != version:
        raise ValueError("Blender add-on version does not match pyproject.toml")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Tag {tag!r} does not match v{version}")
    notes = root / "docs/releases" / f"v{version}.md"
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        raise ValueError(f"Missing release notes: {notes}")
    return version


def check_assets(directory, version):
    wheel_name = f"better_blender_mcp-{version}-py3-none-any.whl"
    addon_name = f"better_blender_bridge-{version}.zip"
    expected = {wheel_name, addon_name}
    if {p.name for p in directory.iterdir()} != expected | {"SHA256SUMS"}:
        raise ValueError("Release must contain exactly the wheel, add-on ZIP and SHA256SUMS")
    seen = set()
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name not in expected or name in seen:
            raise ValueError("Unexpected or duplicate checksum entry")
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Checksum mismatch: {name}")
        seen.add(name)
    if seen != expected:
        raise ValueError("Missing checksum entry")
    with (
        zipfile.ZipFile(directory / wheel_name) as wheel,
        zipfile.ZipFile(directory / addon_name) as addon,
    ):
        bridge_files = {
            name for name in wheel.namelist() if name.startswith("better_blender_bridge/")
        }
        if set(addon.namelist()) != bridge_files:
            raise ValueError("Wheel and ZIP must contain identical bridge files")
        for name in bridge_files:
            if wheel.read(name) != addon.read(name):
                raise ValueError(f"Wheel/ZIP mismatch: {name}")
    return [directory / name for name in sorted(expected | {"SHA256SUMS"})]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--assets", type=Path)
    args = parser.parse_args()
    version = check_version(tag=args.tag)
    if args.assets:
        check_assets(args.assets, version)
    print(f"Release v{version} validated")
