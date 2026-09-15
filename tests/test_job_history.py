import importlib
import json
import sys
import types
from pathlib import Path


def test_job_history_survives_restart_and_marks_interrupted(tmp_path, monkeypatch):
    package = types.ModuleType("test_bridge_package")
    package.__path__ = [
        str(Path(__file__).resolve().parents[1] / "blender_addon/better_blender_bridge")
    ]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    manager_type = importlib.import_module("test_bridge_package.jobs").RenderJobs
    image = tmp_path / "render.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "completed.json").write_text(
        json.dumps(
            {
                "job_id": "completed",
                "state": "completed",
                "created_at": 1,
                "result": {"outputs": [str(image)]},
                "error": None,
            }
        )
    )
    (tmp_path / "running.json").write_text(
        json.dumps(
            {
                "job_id": "running",
                "state": "running",
                "created_at": 2,
                "result": None,
            }
        )
    )
    manager = manager_type(tmp_path)
    assert manager.list_jobs()["total"] == 2
    assert manager.status("running")["state"] == "interrupted"
    assert manager.image("completed")["image"]["mime_type"] == "image/png"
    manager.shutdown()
    restarted = manager_type(tmp_path)
    assert restarted.status("completed")["result"]["outputs"] == [str(image)]
