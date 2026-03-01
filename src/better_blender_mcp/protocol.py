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

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.request_id,
            "method": self.method,
            "params": self.params,
            "token": self.token,
        }


@dataclass(frozen=True)
class BridgeResponse:
    """Single response envelope returned by the Blender bridge."""

    request_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> BridgeResponse:
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

        return cls(request_id=raw_id, ok=ok_raw, result=result, error=error)
