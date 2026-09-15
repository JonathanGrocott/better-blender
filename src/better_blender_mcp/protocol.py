"""Shared protocol types for communication with the Blender bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BridgeRequest:
    """Single request envelope sent to the Blender bridge."""

    request_id: str
    method: str
    params: dict[str, Any]
    token: str
    timeout_seconds: float | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.request_id,
            "method": self.method,
            "params": self.params,
            "token": self.token,
        }
        if self.timeout_seconds is not None:
            payload["timeout_seconds"] = self.timeout_seconds
        return payload


@dataclass(frozen=True)
class BridgeResponse:
    """Single response envelope returned by the Blender bridge."""

    request_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    code: str | None = None

    @classmethod
    def from_json(cls, payload: Any) -> BridgeResponse:
        if not isinstance(payload, dict):
            raise ValueError("Response must be an object")
        raw_id = payload.get("id")
        if not isinstance(raw_id, str):
            raise ValueError("Missing or invalid response id")

        ok_raw = payload.get("ok")
        if not isinstance(ok_raw, bool):
            raise ValueError("Missing or invalid response ok flag")

        result_raw = payload.get("result")
        result: dict[str, Any] | None
        if isinstance(result_raw, dict):
            result = result_raw
        else:
            result = None

        error_raw = payload.get("error")
        if error_raw is None or isinstance(error_raw, str):
            error = error_raw
        else:
            raise ValueError("Invalid error value")

        code = payload.get("code")
        if code is not None and not isinstance(code, str):
            raise ValueError("Invalid error code")
        if ok_raw and (result is None or error is not None):
            raise ValueError("Success requires an object result and no error")
        if not ok_raw and (not error or result_raw is not None):
            raise ValueError("Failure requires an error and no result")
        return cls(request_id=raw_id, ok=ok_raw, result=result, error=error, code=code)
