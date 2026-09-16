"""Independent render owner: survives bridge death long enough to reap its worker."""

import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

from storage import write_json
from workspaces import lease


def supervise(command, directory, record_path, timeout, control):
    directory = Path(directory)
    with lease(directory) as acquired:
        if not acquired or not directory.is_dir():
            raise RuntimeError("Render workspace is unavailable")
        return _supervise_owned(command, directory, record_path, timeout, control)


def owner_state(control):
    """Poll the control pipe without a blocking reader or inherited worker input."""
    descriptor = control.fileno()
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        peek = kernel.PeekNamedPipe
        peek.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        peek.restype = wintypes.BOOL
        available = wintypes.DWORD()
        if not peek(msvcrt.get_osfhandle(descriptor), None, 0, None, ctypes.byref(available), None):
            # A closed owner pipe is a stop signal, including ERROR_BROKEN_PIPE.
            return "interrupted"
        if not available.value:
            return None
    elif not select.select([descriptor], [], [], 0)[0]:
        return None
    message = os.read(descriptor, 128)
    return "cancelled" if message.strip() == b"cancel" else "interrupted"


def _supervise_owned(command, directory, record_path, timeout, control):
    directory, record_path = Path(directory), Path(record_path)
    job = json.loads(record_path.read_text())
    process = None
    started = time.monotonic()
    try:
        # Persist intent before starting Blender. Failure here launches no worker.
        job["state"] = "running"
        write_json(record_path, job)
        with (directory / "worker.log").open("wb") as log:
            reason = owner_state(control)
            if reason is not None:
                job["state"] = reason
            else:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT
                )
                while process.poll() is None:
                    reason = owner_state(control)
                    if reason is not None:
                        job["state"] = reason
                        break
                    if time.monotonic() - started >= timeout and process.poll() is None:
                        job["state"] = "timed_out"
                        break
                    time.sleep(0.1)
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
