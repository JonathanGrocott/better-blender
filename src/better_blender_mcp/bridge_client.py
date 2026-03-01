"""TCP JSON-RPC style client for the Blender local bridge."""

from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass
from typing import Any

from better_blender_mcp.config import BridgeConfig
from better_blender_mcp.protocol import BridgeRequest, BridgeResponse


class BridgeError(RuntimeError):
    """Raised when bridge calls fail."""


@dataclass
class BlenderBridgeClient:
    """Simple request/response client over local TCP with newline-delimited JSON."""

    config: BridgeConfig

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request = BridgeRequest(
            request_id=str(uuid.uuid4()),
            method=method,
            params=params or {},
            token=self.config.token,
        )

        endpoint = (self.config.host, self.config.port)
        with socket.create_connection(endpoint, timeout=self.config.timeout_seconds) as conn:
            conn.settimeout(self.config.timeout_seconds)
            raw_request = json.dumps(request.to_json()).encode("utf-8") + b"\n"
            conn.sendall(raw_request)

            response_line = self._read_line(conn)

        try:
            response_payload = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"Invalid bridge response: {response_line!r}") from exc

        response = BridgeResponse.from_json(response_payload)
        if response.request_id != request.request_id:
            raise BridgeError(
                f"Mismatched response id: expected {request.request_id}, got {response.request_id}"
            )

        if not response.ok:
            raise BridgeError(response.error or "Unknown bridge error")

        return response.result or {}

    @staticmethod
    def _read_line(conn: socket.socket) -> str:
        buffer = bytearray()
        while True:
            chunk = conn.recv(1)
            if not chunk:
                break
            if chunk == b"\n":
                break
            buffer.extend(chunk)

        if not buffer:
            raise BridgeError("No response from Blender bridge")

        return buffer.decode("utf-8")
