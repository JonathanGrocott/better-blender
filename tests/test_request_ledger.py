import importlib
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def test_durable_admission_is_atomic_and_never_replays(tmp_path, monkeypatch):
    package = types.ModuleType("ledger_test_bridge")
    package.__path__ = [
        str(Path(__file__).resolve().parents[1] / "blender_addon/better_blender_bridge")
    ]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    ledger_type = importlib.import_module("ledger_test_bridge.requests").RequestLedger
    path = tmp_path / "requests.sqlite3"
    ledger = ledger_type(path, capacity=2)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: ledger.admit("one", "delete", {"name": "Cube"}), range(20))
        )
    assert sum(results) == 1
    with pytest.raises(ValueError, match="different arguments"):
        ledger.admit("one", "delete", {"name": "Camera"})
    ledger.update("one", "running")
    assert ledger.admit("two", "create", {})
    ledger.update("two", "completed", {"id": "two", "ok": True, "result": {"name": "Created"}})
    ledger.close()
    reopened = ledger_type(path, capacity=2)
    assert reopened.status("one")["state"] == "interrupted"
    assert not reopened.admit("one", "delete", {"name": "Cube"})
    assert reopened.status("two")["response"]["result"]["name"] == "Created"
    with pytest.raises(ValueError, match="journal full"):
        reopened.admit("three", "create", {})
    assert reopened.status("missing")["state"] == "not_found"
    reopened.close()
