"""Bounded render jobs in isolated Blender processes; no bpy access in worker threads."""

import base64
import json
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .storage import write_json


class RenderJobs:
    def __init__(self, storage=None):
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
                    if job["state"] in {"running", "cancelling"}:
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
        with self.lock:
            active = [j for j in self.jobs.values() if j["state"] in {"running", "cancelling"}]
            if self.closed or len(active) >= 2:
                raise ValueError("Render workers busy; wait for a job to finish")
            # Keep at most 32 completed results, without deleting caller-owned outputs.
            finished = [
                key for key, j in self.jobs.items() if j["state"] not in {"running", "cancelling"}
            ]
            for key in finished[:-31]:
                self._forget(key)
            directory = Path(directory)
            request_path = directory / "request.json"
            result_path = directory / "result.json"
            request_path.write_text(json.dumps(request))
            log_path = directory / "worker.log"
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    [
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
                        str(result_path),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            job_id = str(uuid.uuid4())
            self.jobs[job_id] = {
                "job_id": job_id,
                "state": "running",
                "created_at": time.time(),
                "result": None,
                "error": None,
                "process": process,
                "_directory": directory,
                "progress": {"frames_completed": 0, "fraction": None},
            }
            self._persist(self.jobs[job_id])
            watcher = threading.Thread(target=self._watch, args=(job_id, directory), daemon=True)
            self.watchers = [thread for thread in self.watchers if thread.is_alive()]
            self.watchers.append(watcher)
            watcher.start()
            return self.status(job_id)

    def _watch(self, job_id, directory):
        process = self.jobs[job_id]["process"]
        process.wait()
        try:
            result_path = directory / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else None
            with (directory / "worker.log").open("rb") as log:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 4096))
                error = log.read().decode("utf-8", errors="replace")
            with self.lock:
                job = self.jobs[job_id]
                if job["state"] == "cancelling":
                    job["state"] = "cancelled"
                elif process.returncode == 0 and isinstance(result, dict):
                    job["state"] = "completed"
                    job["result"] = result
                    job["progress"] = {
                        "frames_completed": result.get("frames_written"),
                        "fraction": 1.0,
                    }
                else:
                    job["state"] = "failed"
                    job["error"] = error or "Render worker exited without a result"
                job["finished_at"] = time.time()
                self._persist(job)
                finished = [
                    key
                    for key, value in self.jobs.items()
                    if value["state"] not in {"running", "cancelling"}
                ]
                for key in finished[:-32]:
                    self._forget(key)
        except Exception as exc:
            with self.lock:
                self.jobs[job_id].update(state="failed", error=str(exc))
                self._persist(self.jobs[job_id])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

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
            if job["state"] not in {"running", "cancelling"}:
                return self.status(job_id)
            process = job["process"]
            if process.poll() is not None:
                return self.status(job_id)  # The watcher will publish its actual result.
            job["state"] = "cancelling"
            self._persist(job)
            try:
                process.terminate()
            except ProcessLookupError:
                pass

        # Escalation happens outside the Blender main thread.
        def ensure_stopped():
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

        threading.Thread(target=ensure_stopped, daemon=True).start()
        return self.status(job_id)

    def shutdown(self):
        with self.lock:
            self.closed = True
            ids = list(self.jobs)
        for job_id in ids:
            self.cancel(job_id)
        for watcher in self.watchers:
            watcher.join(timeout=3)

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
