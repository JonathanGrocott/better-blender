import importlib
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[1] / "blender_addon/better_blender_bridge"


@pytest.fixture
def jobs_module(monkeypatch):
    package = types.ModuleType("lifecycle_bridge")
    package.__path__ = [str(ADDON)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    return importlib.import_module("lifecycle_bridge.jobs")


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for lifecycle transition"
        time.sleep(0.02)


def test_failed_admission_never_launches_worker(jobs_module, tmp_path, monkeypatch):
    manager = jobs_module.RenderJobs(tmp_path / "history")
    work = tmp_path / "work"
    work.mkdir()

    def fail_write(*args):
        raise OSError("disk full")

    def unexpected_launch(*args, **kwargs):
        pytest.fail("Launched a process without durable admission")

    monkeypatch.setattr(manager, "_persist", fail_write)
    monkeypatch.setattr(jobs_module.subprocess, "Popen", unexpected_launch)
    with pytest.raises(OSError, match="disk full"):
        manager.submit("blender", work / "scene.blend", {}, work)
    assert not work.exists()
    assert not manager.jobs


@pytest.mark.parametrize("scenario", ["deadline", "cancel", "watcher_failure"])
def test_supervised_job_failure_paths(jobs_module, tmp_path, monkeypatch, scenario):
    manager = jobs_module.RenderJobs(
        tmp_path / "history", timeout_seconds=0.3 if scenario == "deadline" else 30
    )
    work = tmp_path / "work"
    work.mkdir()
    heartbeat = tmp_path / "heartbeat"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import time\nfrom pathlib import Path\n"
        f"path = Path({str(heartbeat)!r})\n"
        "while True:\n    path.write_text(str(time.time()))\n    time.sleep(.02)\n"
    )
    real_popen = subprocess.Popen
    processes = []

    def launch(command, **kwargs):
        process = real_popen([*command[:5], sys.executable, str(worker)], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(jobs_module.subprocess, "Popen", launch)
    if scenario == "watcher_failure":

        def fail_start(_self):
            raise RuntimeError("watcher start failed")

        monkeypatch.setattr(jobs_module.threading.Thread, "start", fail_start)
        with pytest.raises(RuntimeError, match="watcher start failed"):
            manager.submit("unused", work / "scene.blend", {}, work)
        assert processes[0].poll() is not None
        assert not work.exists()
        return
    result = manager.submit("unused", work / "scene.blend", {}, work)
    if scenario == "cancel":
        wait_for(heartbeat.exists)
        # Cancellation still works when further parent-side persistence fails.
        monkeypatch.setattr(manager, "_persist", lambda *_: (_ for _ in ()).throw(OSError("full")))
        manager.cancel(result["job_id"])
    wait_for(lambda: manager.status(result["job_id"])["state"] in {"timed_out", "cancelled"})
    manager.shutdown()
    assert not work.exists()
    assert processes[0].poll() is not None
    if heartbeat.exists():
        value = heartbeat.read_text()
        time.sleep(0.15)
        assert heartbeat.read_text() == value
    saved = json.loads(next((tmp_path / "history").glob("*.json")).read_text())
    assert saved["state"] == ("timed_out" if scenario == "deadline" else "cancelled")


def test_supervisor_reaps_worker_after_owner_crash(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    heartbeat = tmp_path / "heartbeat"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import time\nfrom pathlib import Path\n"
        f"path = Path({str(heartbeat)!r})\n"
        "while True:\n    path.write_text(str(time.time()))\n    time.sleep(.02)\n"
    )
    record = tmp_path / "job.json"
    record.write_text(
        json.dumps({"job_id": "crash-test", "state": "queued", "created_at": time.time()})
    )
    owner = tmp_path / "owner.py"
    command = [
        sys.executable,
        str(ADDON / "render_supervisor.py"),
        str(work),
        str(record),
        "10",
        sys.executable,
        str(worker),
    ]
    owner.write_text(
        "import subprocess, time\n"
        f"p = subprocess.Popen({command!r}, stdin=subprocess.PIPE)\n"
        "time.sleep(30)\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(owner)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        wait_for(heartbeat.exists)
        process.kill()
        process.wait(timeout=5)
        wait_for(lambda: not work.exists())
        assert json.loads(record.read_text())["state"] == "interrupted"
        value = heartbeat.read_text()
        time.sleep(0.15)
        assert heartbeat.read_text() == value
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
