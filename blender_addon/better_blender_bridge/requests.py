"""Durable at-most-once admission; interrupted requests are never replayed."""

import hashlib
import json
import sqlite3
import threading
import time


class RequestLedger:
    def __init__(self, path, capacity=10000):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.capacity = capacity
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        try:
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS requests "
                "(id TEXT PRIMARY KEY, fingerprint TEXT, state TEXT, response TEXT, updated REAL)"
            )
            with self.db:
                self.db.execute(
                    "UPDATE requests SET state='interrupted' WHERE state IN ('queued', 'running')"
                )
        except Exception:
            self.db.close()
            raise

    def admit(self, identifier, method, params):
        fingerprint = hashlib.sha256(
            json.dumps([method, params], sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT fingerprint FROM requests WHERE id=?", (identifier,)
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise ValueError("Request ID already belongs to different arguments")
                return False
            if self.db.execute("SELECT count(*) FROM requests").fetchone()[0] >= self.capacity:
                raise ValueError("Request journal full; archive it while the bridge is stopped")
            self.db.execute(
                "INSERT INTO requests VALUES (?, ?, 'queued', NULL, ?)",
                (identifier, fingerprint, time.time()),
            )
            return True

    def update(self, identifier, state, response=None):
        if response is not None:
            encoded = json.dumps(response, allow_nan=False)
            if len(encoded.encode()) > 262144:
                encoded = json.dumps(
                    {
                        "id": identifier,
                        "ok": False,
                        "code": "RESULT_NOT_RETAINED",
                        "error": "Operation finished; result too large to retain. Do not repeat.",
                    }
                )
        else:
            encoded = None
        with self.lock, self.db:
            self.db.execute(
                "UPDATE requests SET state=?, response=?, updated=? WHERE id=?",
                (state, encoded, time.time(), identifier),
            )

    def status(self, identifier):
        with self.lock:
            row = self.db.execute(
                "SELECT state, response, updated FROM requests WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            return {"request_id": identifier, "state": "not_found"}
        return {
            "request_id": identifier,
            "state": row[0],
            "response": json.loads(row[1]) if row[1] else None,
            "updated_at": row[2],
        }

    def stats(self):
        with self.lock:
            rows = self.db.execute("SELECT state, count(*) FROM requests GROUP BY state").fetchall()
        states = dict(rows)
        return {"states": states, "count": sum(states.values()), "capacity": self.capacity}

    def close(self):
        with self.lock:
            self.db.close()
