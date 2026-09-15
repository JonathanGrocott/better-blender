"""Explicit whole-file recovery snapshots; must be called on Blender's main thread."""

import json
import shutil
import time
import uuid
from pathlib import Path

import bpy

from . import assets
from .storage import state_directory, write_json


def create(label="Checkpoint", protected=()):
    identifier = str(uuid.uuid4())
    directory = state_directory() / "checkpoints" / identifier
    directory.mkdir(parents=True)
    filepath = directory / "snapshot.blend"
    original = bpy.data.filepath
    external_paths = assets.paths()
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
            "external_assets": external_paths,
            "size_bytes": filepath.stat().st_size,
        }
        if filepath.stat().st_size > _limits()["max_bytes"]:
            raise ValueError("Checkpoint exceeds the configured byte limit")
        write_json(directory / "metadata.json", metadata)
        metadata["retention"] = prune((*protected, identifier))
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


def restore(checkpoint_id, backup_current=True, allow_missing_assets=False):
    identifier = str(uuid.UUID(checkpoint_id))
    source = state_directory() / "checkpoints" / identifier / "snapshot.blend"
    if not source.exists():
        raise ValueError("Checkpoint not found")
    metadata = json.loads(source.with_name("metadata.json").read_text())
    report = assets.inspect(metadata.get("external_assets", []))
    report["manifest_available"] = "external_assets" in metadata
    if not allow_missing_assets and (not report["complete"] or not report["manifest_available"]):
        raise ValueError(
            "Checkpoint assets are missing or unverified. Use check_assets "
            "or explicitly allow_missing_assets to restore anyway."
        )
    backup = (
        create("Before checkpoint restore", protected=(identifier,)) if backup_current else None
    )
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
        "assets": report,
    }


DEFAULT_LIMITS = {"max_count": 20, "max_bytes": 2 * 1024 * 1024 * 1024}


def _limits():
    file = state_directory() / "checkpoint-limits.json"
    return json.loads(file.read_text()) if file.exists() else dict(DEFAULT_LIMITS)


def usage():
    directory = state_directory() / "checkpoints"
    snapshots = list(directory.glob("*/snapshot.blend"))
    all_bytes = sum(file.stat().st_size for file in directory.rglob("*") if file.is_file())
    managed_bytes = sum(file.stat().st_size for file in snapshots)
    limits = _limits()
    return {
        "count": len(snapshots),
        "snapshot_bytes": managed_bytes,
        "other_bytes": all_bytes - managed_bytes,
        "total_bytes": all_bytes,
        "limits": limits,
        "within_limits": len(snapshots) <= limits["max_count"]
        and managed_bytes <= limits["max_bytes"],
    }


def delete(checkpoint_id):
    identifier = str(uuid.UUID(checkpoint_id))
    directory = state_directory() / "checkpoints" / identifier
    snapshot = directory / "snapshot.blend"
    if not snapshot.exists():
        raise ValueError("Checkpoint not found")
    if bpy.data.filepath and snapshot.resolve() == Path(bpy.data.filepath).resolve():
        raise ValueError("Cannot delete the currently open checkpoint file")
    reclaimed = snapshot.stat().st_size
    snapshot.unlink()
    (directory / "metadata.json").unlink(missing_ok=True)
    # Restored documents are user working files and must survive checkpoint deletion.
    retained = [str(file) for file in directory.iterdir()]
    if not retained:
        directory.rmdir()
    return {
        "deleted_checkpoint": identifier,
        "reclaimed_bytes": reclaimed,
        "retained_files": retained,
    }


def prune(protected=()):
    records = list_checkpoints(0, 1000000)["checkpoints"]
    deleted = []
    for record in reversed(records):
        if usage()["within_limits"]:
            break
        if record["checkpoint_id"] in protected or record["filepath"] == bpy.data.filepath:
            continue
        deleted.append(delete(record["checkpoint_id"])["deleted_checkpoint"])
    return {"deleted": deleted, **usage()}


def configure(max_count, max_bytes):
    if max_count < 1 or max_bytes < 1:
        raise ValueError("Retention limits must be positive")
    write_json(
        state_directory() / "checkpoint-limits.json",
        {"max_count": max_count, "max_bytes": max_bytes},
    )
    return prune()


def check_assets(checkpoint_id=None):
    if checkpoint_id is None:
        return assets.inspect()
    identifier = str(uuid.UUID(checkpoint_id))
    file = state_directory() / "checkpoints" / identifier / "metadata.json"
    if not file.exists():
        raise ValueError("Checkpoint not found")
    metadata = json.loads(file.read_text())
    return {
        **assets.inspect(metadata.get("external_assets", [])),
        "manifest_available": "external_assets" in metadata,
    }
