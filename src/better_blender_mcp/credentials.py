"""Load the packaged dependency-free credential helper without importing bpy."""

import importlib.util
from pathlib import Path
from typing import Any


def _helper() -> Any:
    package = importlib.util.find_spec("better_blender_bridge")
    if package is None or package.origin is None:
        raise RuntimeError("Packaged bridge is missing; reinstall better-blender-mcp")
    spec = importlib.util.spec_from_file_location(
        "_better_blender_credentials", Path(package.origin).with_name("credentials.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Credential helper is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_token() -> str:
    return str(_helper().ensure_token())


def read_token() -> str:
    path = Path(_helper().token_path())
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""
