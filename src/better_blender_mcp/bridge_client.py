"""TCP JSON-RPC style client for the Blender local bridge."""

from __future__ import annotations

import asyncio
import json
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any

from better_blender_mcp.config import BridgeConfig
from better_blender_mcp.protocol import BridgeRequest, BridgeResponse

MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class BridgeError(RuntimeError):
    """A transport or Blender failure with a stable machine-readable code."""

    def __init__(self, message: str, code: str = "BRIDGE_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class BlenderBridgeClient:
    """Simple request/response client over local TCP with newline-delimited JSON."""

    config: BridgeConfig

    async def acall(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Wait for bridge I/O without blocking the MCP event loop.

        Cancelling the await does not cancel a command already executing in Blender.
        """
        return await asyncio.to_thread(self.call, method, params)

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request = BridgeRequest(
            request_id=str(uuid.uuid4()),
            method=method,
            params=params or {},
            token=self.config.token,
            timeout_seconds=self.config.timeout_seconds,
        )

        sent = False
        try:
            raw_request = json.dumps(request.to_json(), allow_nan=False).encode("utf-8") + b"\n"
            if len(raw_request) > MAX_REQUEST_BYTES:
                raise BridgeError("Request exceeds 1 MiB limit", "REQUEST_TOO_LARGE")
            endpoint = (self.config.host, self.config.port)
            with socket.create_connection(endpoint, timeout=self.config.timeout_seconds) as conn:
                deadline = time.monotonic() + self.config.timeout_seconds + 1.0
                conn.settimeout(self.config.timeout_seconds + 1.0)
                sent = True
                conn.sendall(raw_request)
                response_line = self._read_line(conn, deadline)
            response = BridgeResponse.from_json(json.loads(response_line))
        except (ValueError, UnicodeError) as exc:
            raise BridgeError(f"Invalid bridge message: {exc}", "INVALID_MESSAGE") from exc
        except OSError as exc:
            code = "OUTCOME_UNKNOWN" if sent else "CONNECTION_ERROR"
            detail = " Operation outcome unknown; do not retry automatically." if sent else ""
            raise BridgeError(f"Bridge connection failed: {exc}.{detail}", code) from exc

        if response.code == "BUSY" and response.request_id == "unknown":
            raise BridgeError(response.error or "Bridge busy", "BUSY")
        if response.request_id != request.request_id:
            raise BridgeError(
                f"Mismatched response id: expected {request.request_id}, got {response.request_id}"
            )

        if not response.ok:
            raise BridgeError(
                response.error or "Unknown bridge error", response.code or "COMMAND_ERROR"
            )

        return response.result or {}

    @staticmethod
    def _read_line(conn: socket.socket, deadline: float | None = None) -> str:
        buffer = bytearray()
        while len(buffer) <= MAX_RESPONSE_BYTES:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Bridge response deadline exceeded")
                conn.settimeout(remaining)
            chunk = conn.recv(min(65536, MAX_RESPONSE_BYTES + 1 - len(buffer)))
            if not chunk:
                raise BridgeError("Truncated bridge response", "INVALID_MESSAGE")
            buffer.extend(chunk)
            newline = buffer.find(b"\n")
            if newline >= 0:
                if newline + 1 > MAX_RESPONSE_BYTES:
                    break
                return buffer[:newline].decode("utf-8")
        raise BridgeError("Response exceeds 16 MiB limit", "RESPONSE_TOO_LARGE")
