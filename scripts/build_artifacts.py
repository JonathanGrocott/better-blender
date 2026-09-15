"""Build matching unsigned wheel/add-on ZIP artifacts with SHA-256 checksums."""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="dist")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="bb-release-") as temporary:
    source = Path(temporary) / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "src", "blender_addon"):
        src, dest = root / name, source / name
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        else:
            shutil.copy2(src, dest)
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", str(source), "-w", temporary],
        check=True,
    )
    wheel = next(Path(temporary).glob("*.whl"))
    wheel_target = output / wheel.name
    shutil.copy2(wheel, wheel_target)
    version = wheel.name.split("-")[1]
    addon_target = output / f"better_blender_bridge-{version}.zip"
    with (
        zipfile.ZipFile(wheel) as package,
        zipfile.ZipFile(
            addon_target,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as addon,
    ):
        names = [name for name in package.namelist() if name.startswith("better_blender_bridge/")]
        assert "better_blender_bridge/__init__.py" in names
        assert "better_blender_bridge/schemas.json" in names
        for name in sorted(names):
            addon.writestr(name, package.read(name))
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in (wheel_target, addon_target)
    )
    (output / "SHA256SUMS").write_text(checksums)
    print(f"Artifacts ready in {output}")
