"""Command-line entrypoint for Better Blender MCP."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from better_blender_mcp.config import load_config_from_env
from better_blender_mcp.mcp_server import run_server


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        run_server()
        return 0

    if args.command == "doctor":
        return _run_doctor()

    if args.command == "print-config":
        _print_config(target=args.client)
        return 0

    if args.command == "install-addon":
        return _install_addon(version=args.blender_version, destination=args.destination)

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="better-blender-mcp")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="Run the MCP server")
    subparsers.add_parser("doctor", help="Run local environment diagnostics")

    print_config = subparsers.add_parser("print-config", help="Print MCP client config snippets")
    print_config.add_argument(
        "--client",
        choices=["generic", "claude-desktop", "cursor"],
        default="generic",
        help="Target client config format",
    )

    install_addon = subparsers.add_parser(
        "install-addon", help="Install Blender add-on into scripts/addons"
    )
    install_addon.add_argument(
        "--blender-version",
        required=True,
        help="Blender version (major.minor or major.minor.patch), example: 4.2 or 3.4.1",
    )
    install_addon.add_argument(
        "--destination",
        default=None,
        help="Optional explicit addon install directory (defaults to user scripts/addons path)",
    )

    return parser


def _run_doctor() -> int:
    config = load_config_from_env()
    blender_path = _find_blender_executable()

    report = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "bridge": {
            "host": config.bridge.host,
            "port": config.bridge.port,
            "token_configured": config.bridge.token != "change-me",
            "timeout_seconds": config.bridge.timeout_seconds,
        },
        "blender_executable": str(blender_path) if blender_path else None,
    }

    print(json.dumps(report, indent=2))

    if blender_path is None:
        print("doctor: Blender executable not found in PATH or common locations", file=sys.stderr)
        return 1

    return 0


def _find_blender_executable() -> Path | None:
    if blender := shutil.which("blender"):
        return Path(blender)

    candidates = [
        "/Applications/Blender.app/Contents/MacOS/Blender",
        os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
        "C:/Program Files/Blender Foundation/Blender/blender.exe",
        "/usr/bin/blender",
        "/snap/bin/blender",
    ]

    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path

    return None


def _print_config(target: str) -> None:
    """Print a minimal stdio MCP config snippet."""

    base = {
        "command": "better-blender-mcp",
        "args": ["serve"],
        "env": {
            "BETTER_BLENDER_HOST": "127.0.0.1",
            "BETTER_BLENDER_PORT": "8765",
            "BETTER_BLENDER_TOKEN": "change-me",
        },
    }

    if target == "generic":
        print(json.dumps({"better-blender": base}, indent=2))
        return

    if target == "claude-desktop":
        print(json.dumps({"mcpServers": {"better-blender": base}}, indent=2))
        return

    if target == "cursor":
        print(json.dumps({"mcpServers": {"better-blender": base}}, indent=2))


def _install_addon(version: str, destination: str | None) -> int:
    addon_source = Path(__file__).resolve().parents[2] / "blender_addon" / "better_blender_bridge"
    if not addon_source.exists():
        print(f"Add-on source not found: {addon_source}", file=sys.stderr)
        return 1

    try:
        scripts_version = _normalize_blender_scripts_version(version)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    addon_target_dir = Path(destination) if destination else _default_addon_dir(scripts_version)
    addon_target_dir.mkdir(parents=True, exist_ok=True)
    target = addon_target_dir / "better_blender_bridge"

    if target.exists():
        shutil.rmtree(target)

    shutil.copytree(addon_source, target)
    print(f"Installed add-on to: {target}")
    return 0


def _normalize_blender_scripts_version(version: str) -> str:
    trimmed = version.strip()
    parts = trimmed.split(".")
    if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
        raise ValueError(
            "Invalid --blender-version. Expected major.minor or major.minor.patch "
            "(for example: 4.2 or 3.4.1)."
        )

    major = int(parts[0])
    minor = int(parts[1])
    return f"{major}.{minor}"


def _default_addon_dir(version: str) -> Path:
    system = platform.system().lower()

    if system == "darwin":
        return Path.home() / "Library/Application Support/Blender" / version / "scripts/addons"

    if system == "windows":
        appdata = os.getenv("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is not set")
        return Path(appdata) / "Blender Foundation/Blender" / version / "scripts/addons"

    return Path.home() / ".config/blender" / version / "scripts/addons"


if __name__ == "__main__":
    raise SystemExit(main())
