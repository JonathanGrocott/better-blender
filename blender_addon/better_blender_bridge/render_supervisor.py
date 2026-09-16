"""Independent render owner: survives bridge death long enough to reap its worker."""

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from storage import write_json


def supervise(command, directory, record_path, timeout, control):
    directory, record_path = Path(directory), Path(record_path)
    job = json.loads(record_path.read_text())
    stopped = threading.Event()
    reason = ["interrupted"]

    def monitor_owner():
        try:
            message = control.readline()
            reason[0] = "cancelled" if message.strip() == b"cancel" else "interrupted"
        finally:
            stopped.set()

    threading.Thread(target=monitor_owner, daemon=True).start()
    process = None
    started = time.monotonic()
    try:
        # Persist intent before starting Blender. Failure here launches no worker.
        job["state"] = "running"
        write_json(record_path, job)
        with (directory / "worker.log").open("wb") as log:
            if stopped.is_set():
                job["state"] = reason[0]
            else:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                while process.poll() is None:
                    if stopped.wait(0.1):
                        job["state"] = reason[0]
                        break
                    if time.monotonic() - started >= timeout:
                        job["state"] = "timed_out"
                        break
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                if job["state"] == "running":
                    result_path = directory / "result.json"
                    if process.returncode == 0 and result_path.exists():
                        result = json.loads(result_path.read_text())
                        if not isinstance(result, dict):
                            raise ValueError("Invalid render result")
                        job.update(
                            state="completed",
                            result=result,
                            progress={
                                "frames_completed": result.get("frames_written"),
                                "fraction": 1.0,
                            },
                        )
                    else:
                        job["state"] = "failed"
        if job["state"] != "completed":
            with (directory / "worker.log").open("rb") as log:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 4096))
                detail = log.read().decode("utf-8", errors="replace")
            job["error"] = {
                "timed_out": "Render exceeded its runtime limit",
                "interrupted": "Bridge connection closed before render completion",
                "cancelled": "Render cancelled",
            }.get(job["state"], detail or "Render worker exited without a result")
    except Exception as exc:
        job.update(state="failed", error=str(exc))
    finally:
        # Every exception path must reap a worker before removing its input files.
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        job["finished_at"] = time.time()
        try:
            write_json(record_path, job)
        finally:
            shutil.rmtree(directory, ignore_errors=True)
    return job


if __name__ == "__main__":
    directory, record_path, timeout, *command = sys.argv[1:]
    supervise(command, directory, record_path, float(timeout), sys.stdin.buffer)
