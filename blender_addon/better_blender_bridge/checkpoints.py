"""Explicit whole-file recovery snapshots; must be called on Blender's main thread."""

import json
import shutil
import time
import uuid

import bpy

from .storage import state_directory, write_json


def create(label="Checkpoint"):
    identifier = str(uuid.uuid4())
    directory = state_directory() / "checkpoints" / identifier
    directory.mkdir(parents=True)
    filepath = directory / "snapshot.blend"
    original = bpy.data.filepath
    try:
        result = bpy.ops.wm.save_as_mainfile(filepath=str(filepath), copy=True, relative_remap=True)
        if "FINISHED" not in result:
            raise RuntimeError("Could not save checkpoint")
        metadata = {
            "checkpoint_id": identifier,
            "label": label,
            "created_at": time.time(),
            "original_filepath": original,
            "filepath": str(filepath),
        }
        write_json(directory / "metadata.json", metadata)
        return metadata
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def list_checkpoints(offset=0, limit=50):
    records = []
    for file in (state_directory() / "checkpoints").glob("*/metadata.json"):
        try:
            records.append(json.loads(file.read_text()))
        except (OSError, ValueError):
            continue
    records.sort(key=lambda item: item["created_at"], reverse=True)
    return {
        "checkpoints": records[offset : offset + limit],
        "total": len(records),
        "next_offset": offset + limit if offset + limit < len(records) else None,
    }


def restore(checkpoint_id, backup_current=True):
    identifier = str(uuid.UUID(checkpoint_id))
    source = state_directory() / "checkpoints" / identifier / "snapshot.blend"
    if not source.exists():
        raise ValueError("Checkpoint not found")
    backup = create("Before checkpoint restore") if backup_current else None
    # Keep the stored snapshot immutable. A restored document is a separate working copy.
    # Keep it beside the snapshot so remapped relative asset paths still resolve.
    restored = source.with_name("restored-" + uuid.uuid4().hex + ".blend")
    shutil.copy2(source, restored)
    result = bpy.ops.wm.open_mainfile(filepath=str(restored), use_scripts=False)
    if "FINISHED" not in result:
        raise RuntimeError("Could not restore checkpoint")
    return {
        "restored_checkpoint": identifier,
        "filepath": str(restored),
        "recovery_checkpoint": backup,
        "save_required": True,
    }
