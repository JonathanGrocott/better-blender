"""Local state shared across bridge restarts."""

import json
import os
import uuid
from pathlib import Path


def state_directory():
    path = Path(os.environ.get("BETTER_BLENDER_STATE_DIR", str(Path.home() / ".better-blender")))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
