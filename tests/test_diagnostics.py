import importlib
import json
import sys
import types
from pathlib import Path


def test_diagnostics_bounds_history_and_rotates_logs(tmp_path, monkeypatch):
    package = types.ModuleType("diagnostics_test_bridge")
    package.__path__ = [
        str(Path(__file__).resolve().parents[1] / "blender_addon/better_blender_bridge")
    ]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    diagnostic_type = importlib.import_module("diagnostics_test_bridge.diagnostics").Diagnostics
    log = tmp_path / "requests.jsonl"
    diagnostics = diagnostic_type(log)
    diagnostics.handler.maxBytes = 500
    for index in range(100):
        diagnostics.record(
            str(index),
            "edit",
            {
                "ok": False,
                "code": "DOCUMENT_CHANGED",
                "error": "private document contents",
            },
            0.01,
        )
    status = diagnostics.snapshot()
    assert len(status["recent_failures"]) == 50
    assert status["counts"]["response"] == 100
    assert status["recent_failures"][-1]["duration_ms"] == 10
    diagnostics.close()
    files = list(tmp_path.glob("requests.jsonl*"))
    assert 1 < len(files) <= 4
    for file in files:
        assert "private document contents" not in file.read_text()
        for line in file.read_text().splitlines():
            assert json.loads(line)["code"] == "DOCUMENT_CHANGED"
