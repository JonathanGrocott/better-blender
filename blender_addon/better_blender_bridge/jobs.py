"""Bounded render jobs in isolated Blender processes; no bpy access in worker threads."""

import json
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path


class RenderJobs:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = {}
        self.closed = False

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
                del self.jobs[key]
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
            }
            threading.Thread(target=self._watch, args=(job_id, directory), daemon=True).start()
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
                else:
                    job["state"] = "failed"
                    job["error"] = error or "Render worker exited without a result"
                job["finished_at"] = time.time()
        except Exception as exc:
            with self.lock:
                self.jobs[job_id].update(state="failed", error=str(exc))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def status(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError(f"Unknown or expired job: {job_id}")
            return {key: value for key, value in self.jobs[job_id].items() if key != "process"}

    def cancel(self, job_id):
        with self.lock:
            self.status(job_id)
            job = self.jobs[job_id]
            if job["state"] not in {"running", "cancelling"}:
                return self.status(job_id)
            job["state"] = "cancelling"
            process = job["process"]
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
