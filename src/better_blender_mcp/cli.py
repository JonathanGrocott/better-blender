"""Command-line entrypoint for Better Blender MCP."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from better_blender_mcp.bridge_client import BlenderBridgeClient
from better_blender_mcp.config import load_config_from_env
from better_blender_mcp.credentials import ensure_token
from better_blender_mcp.mcp_server import run_server


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        ensure_token()
        print("Generated token is ready; leave Blender’s token override blank.")
        return 0

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

    subparsers.add_parser("setup", help="Create a unique per-user bridge token")
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

    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "bridge": {
            "host": config.bridge.host,
            "port": config.bridge.port,
            "token_configured": bool(config.bridge.token) and config.bridge.token != "change-me",
            "timeout_seconds": config.bridge.timeout_seconds,
        },
        "blender_executable": str(blender_path) if blender_path else None,
    }

    healthy = False
    try:
        status = BlenderBridgeClient(
            replace(
                config.bridge,
                timeout_seconds=min(config.bridge.timeout_seconds, 3.0),
            )
        ).call("health")
        version = tuple(
            int(v) for v in str(status.get("blender_version", "0")).split()[0].split(".")
        )
        capabilities = status.get("capabilities", {})
        required = {
            "render_jobs",
            "inline_images",
            "strict_inputs",
            "checkpoints",
            "node_inspection",
            "persistent_jobs",
            "document_guards",
            "durable_requests",
            "access_controls",
            "checkpoint_retention",
            "diagnostics",
        }
        missing = sorted(key for key in required if capabilities.get(key) is not True)
        healthy = status.get("protocol_version") == 1 and version >= (3, 4, 1) and not missing
        report["bridge"]["missing_capabilities"] = missing
        report["bridge"]["connected"] = True
        report["bridge"]["compatible"] = healthy
        report["bridge"]["runtime"] = status
    except (OSError, ValueError, RuntimeError) as exc:
        report["bridge"]["connected"] = False
        report["bridge"]["error"] = str(exc)
    print(json.dumps(report, indent=2))

    if blender_path is None:
        print("doctor: Blender executable not found in PATH or common locations", file=sys.stderr)
        return 1

    return 0 if healthy else 1


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
            "BETTER_BLENDER_TOKEN": load_config_from_env().bridge.token or ensure_token(),
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
    # Looking up the package avoids importing bpy outside Blender.
    spec = importlib.util.find_spec("better_blender_bridge")
    if spec is None or spec.origin is None:
        print("Packaged Blender add-on not found. Reinstall better-blender-mcp.", file=sys.stderr)
        return 1
    addon_source = Path(spec.origin).parent

    try:
        scripts_version = _normalize_blender_scripts_version(version)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    addon_target_dir = Path(destination) if destination else _default_addon_dir(scripts_version)
    addon_target_dir.mkdir(parents=True, exist_ok=True)
    target = addon_target_dir / "better_blender_bridge"

    if target.resolve() == addon_source.resolve():
        print(
            "Destination is the source package; choose a Blender add-ons directory.",
            file=sys.stderr,
        )
        return 1
    staging = Path(tempfile.mkdtemp(prefix=".better-blender-install-", dir=addon_target_dir))
    incoming, backup = staging / "incoming", staging / "previous"
    preserve_backup = False
    try:
        shutil.copytree(
            addon_source, incoming, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        if target.exists():
            target.rename(backup)
        try:
            incoming.rename(target)
        except OSError:
            if backup.exists():
                try:
                    backup.rename(target)
                except OSError:
                    preserve_backup = True
                    print(f"Previous add-on preserved at {backup}", file=sys.stderr)
            raise
    except OSError as exc:
        print(f"Add-on installation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not preserve_backup:
            shutil.rmtree(staging, ignore_errors=True)

    ensure_token()
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
