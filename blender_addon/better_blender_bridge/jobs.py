"""Bounded render jobs in isolated Blender processes; no bpy access in worker threads."""

import base64
import json
import math
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .storage import write_json


class RenderJobs:
    def __init__(self, storage=None, timeout_seconds=3600):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Render timeout must be finite and positive")
        self.timeout_seconds = timeout_seconds
        self._temporary_storage = None
        self.lock = threading.RLock()
        self.jobs = {}
        self.closed = False
        self.storage = Path(storage) if storage else None
        self.watchers = []
        if self.storage:
            self.storage.mkdir(parents=True, exist_ok=True)
            for path in self.storage.glob("*.json"):
                try:
                    job = json.loads(path.read_text())
                    if job["state"] in {"queued", "running", "cancelling"}:
                        job.update(
                            state="interrupted", error="Bridge stopped before recording completion"
                        )
                    self.jobs[job["job_id"]] = job
                except (ValueError, KeyError, OSError):
                    continue

        self.jobs = dict(sorted(self.jobs.items(), key=lambda item: item[1]["created_at"]))

    def _persist(self, job):
        if self.storage:
            write_json(self.storage / (job["job_id"] + ".json"), self._public(job))

    @staticmethod
    def _public(job):
        return {
            key: value for key, value in job.items() if key != "process" and not key.startswith("_")
        }

    def _forget(self, key):
        del self.jobs[key]
        if self.storage:
            (self.storage / (key + ".json")).unlink(missing_ok=True)

    def submit(self, binary, snapshot, request, directory):
        directory = Path(directory)
        process = None
        job_id = str(uuid.uuid4())
        with self.lock:
            try:
                active = [
                    j
                    for j in self.jobs.values()
                    if j["state"] in {"queued", "running", "cancelling"}
                ]
                if self.closed or len(active) >= 2:
                    raise ValueError("Render workers busy; wait for a job to finish")
                finished = [
                    key
                    for key, j in self.jobs.items()
                    if j["state"] not in {"queued", "running", "cancelling"}
                ]
                for key in finished[:-31]:
                    self._forget(key)
                if self.storage is None:
                    self._temporary_storage = tempfile.TemporaryDirectory(prefix="bb-job-history-")
                    self.storage = Path(self._temporary_storage.name)
                request_path = directory / "request.json"
                request_path.write_text(json.dumps(request))
                job = {
                    "job_id": job_id,
                    "state": "queued",
                    "created_at": time.time(),
                    "result": None,
                    "error": None,
                    "timeout_seconds": self.timeout_seconds,
                    "progress": {"frames_completed": 0, "fraction": None},
                    "_directory": directory,
                }
                # Failure to persist admission must never launch a process.
                self._persist(job)
                command = [
                    binary,
                    "--background",
                    str(snapshot),
                    "--disable-autoexec",
                    "--python-exit-code",
                    "1",
                    "--python",
                    str(Path(__file__).with_name("render_worker.py")),
                    "--",
                    str(request_path),
                    str(directory / "result.json"),
                ]
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("render_supervisor.py")),
                        str(directory),
                        str(self.storage / (job_id + ".json")),
                        str(self.timeout_seconds),
                        *command,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                job.update(state="running", process=process)
                self.jobs[job_id] = job
                watcher = threading.Thread(target=self._watch, args=(job_id,), daemon=True)
                self.watchers = [thread for thread in self.watchers if thread.is_alive()]
                watcher.start()
                self.watchers.append(watcher)
                return self.status(job_id)
            except Exception:
                if process is not None:
                    self._stop_process(process)
                    # Supervisor owns worker termination; do not kill it before it reaps Blender.
                    process.wait()
                self.jobs.pop(job_id, None)
                if self.storage:
                    (self.storage / (job_id + ".json")).unlink(missing_ok=True)
                shutil.rmtree(directory, ignore_errors=True)
                raise

    @staticmethod
    def _stop_process(process):
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.write(b"cancel\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

    def _watch(self, job_id):
        process = self.jobs[job_id]["process"]
        process.wait()
        with self.lock:
            if process.stdin is not None:
                process.stdin.close()
            job = self.jobs[job_id]
            try:
                saved = json.loads((self.storage / (job_id + ".json")).read_text())
                if saved["state"] in {"queued", "running", "cancelling"}:
                    raise ValueError("Supervisor exited without a durable terminal result")
                job.update(saved)
            except (OSError, ValueError, KeyError) as exc:
                job.update(state="failed", error=str(exc), finished_at=time.time())
                try:
                    self._persist(job)
                except OSError as persist_error:
                    job["persistence_error"] = str(persist_error)
            finally:
                shutil.rmtree(job["_directory"], ignore_errors=True)
            finished = [
                key
                for key, value in self.jobs.items()
                if value["state"] not in {"queued", "running", "cancelling"}
            ]
            for key in finished[:-32]:
                try:
                    self._forget(key)
                except OSError:
                    pass

    def status(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError(f"Unknown or expired job: {job_id}")
            job = self.jobs[job_id]
            if job["state"] in {"running", "cancelling"} and "_directory" in job:
                try:
                    job["progress"] = json.loads((job["_directory"] / "progress.json").read_text())
                except (OSError, ValueError):
                    pass
            return self._public(job)

    def cancel(self, job_id):
        with self.lock:
            self.status(job_id)
            job = self.jobs[job_id]
            if job["state"] not in {"queued", "running", "cancelling"}:
                return self.status(job_id)
            if job["process"].poll() is not None:
                return self.status(job_id)
            job["state"] = "cancelling"
            # Cancellation must work even if storage is full/unwritable.
            self._stop_process(job["process"])
            return self.status(job_id)

    def shutdown(self):
        with self.lock:
            self.closed = True
            ids = list(self.jobs)
        for job_id in ids:
            self.cancel(job_id)
        for watcher in self.watchers:
            watcher.join(timeout=10)
            if watcher.is_alive():
                raise RuntimeError("Render supervisor did not finish shutdown within 10 seconds")
        if self._temporary_storage is not None:
            self._temporary_storage.cleanup()

    def list_jobs(self, offset=0, limit=50):
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return {
                "jobs": [self.status(j["job_id"]) for j in jobs[offset : offset + limit]],
                "total": len(jobs),
                "next_offset": offset + limit if offset + limit < len(jobs) else None,
            }

    def image(self, job_id, index=0):
        job = self.status(job_id)
        outputs = (job.get("result") or {}).get("outputs", [])
        if index < 0 or index >= len(outputs):
            raise ValueError("No image at this index; inspect completed job outputs")
        path = Path(outputs[index])
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
            path.suffix.lower()
        )
        if mime is None:
            raise ValueError("Inline images support PNG and JPEG outputs")
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Output missing or exceeds the 8 MiB inline image limit")
        return {
            "job_id": job_id,
            "filepath": str(path),
            "image": {
                "mime_type": mime,
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            },
        }
