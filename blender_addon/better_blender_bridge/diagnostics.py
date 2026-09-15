"""Bounded, structured diagnostics without tokens, arguments, or scene contents."""

import json
import logging
import threading
import time
from collections import Counter, deque
from logging.handlers import RotatingFileHandler


class Diagnostics:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        self.counts = Counter()
        self.failures = deque(maxlen=50)
        self.connections = 0
        self.handler = RotatingFileHandler(path, maxBytes=1048576, backupCount=3, encoding="utf-8")
        self.logger = logging.Logger("better-blender." + path.stem)
        self.logger.addHandler(self.handler)

    def connection(self, delta):
        with self.lock:
            self.connections += delta

    def record(self, request_id, method, response, duration, phase="response"):
        event = {
            "timestamp": time.time(),
            "request_id": request_id,
            "method": method,
            "phase": phase,
            "ok": response.get("ok", False),
            "code": response.get("code", "OK" if response.get("ok") else "COMMAND_ERROR"),
            "duration_ms": round(duration * 1000, 3),
        }
        with self.lock:
            self.counts[phase] += 1
            if not event["ok"]:
                self.counts["failures"] += 1
                self.failures.append(event)
            try:
                self.logger.info(json.dumps(event))
            except OSError:
                self.counts["log_write_failures"] += 1

    def snapshot(self):
        with self.lock:
            return {
                "counts": dict(self.counts),
                "active_connections": self.connections,
                "recent_failures": list(self.failures),
                "log_path": str(self.path),
                "log_max_bytes": 1048576,
                "log_backups": 3,
            }

    def close(self):
        self.handler.close()
