"""Shared per-user credentials, usable without importing Blender."""

import os
import secrets
from pathlib import Path


def token_path():
    directory = Path(
        os.environ.get("BETTER_BLENDER_STATE_DIR", str(Path.home() / ".better-blender"))
    )
    return directory / "token"


def ensure_token():
    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Publish a complete file atomically. A concurrent setup keeps the winning token.
    temporary = path.with_name(".token-" + secrets.token_hex(8))
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(secrets.token_urlsafe(32) + "\n")
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise ValueError("Stored bridge token is invalid; replace it with a generated token")
    return value
