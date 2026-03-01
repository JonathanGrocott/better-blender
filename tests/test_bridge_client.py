from __future__ import annotations

import json
import socketserver
import threading

import pytest

from better_blender_mcp.bridge_client import BlenderBridgeClient, BridgeError
from better_blender_mcp.config import BridgeConfig


class _FakeHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline()
        payload = json.loads(line.decode("utf-8"))

        if payload["method"] == "fail":
            response = {"id": payload["id"], "ok": False, "error": "boom"}
        else:
            response = {"id": payload["id"], "ok": True, "result": {"echo": payload["method"]}}

        self.wfile.write(json.dumps(response).encode("utf-8") + b"\n")
        self.wfile.flush()


class _FakeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def _start_server() -> tuple[_FakeServer, threading.Thread]:
    server = _FakeServer(("127.0.0.1", 0), _FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_bridge_client_success() -> None:
    server, thread = _start_server()
    host, port = server.server_address

    client = BlenderBridgeClient(
        BridgeConfig(host=host, port=int(port), token="secret", timeout_seconds=1.0)
    )
    result = client.call("health")

    assert result == {"echo": "health"}

    server.shutdown()
    server.server_close()
    thread.join(timeout=1.0)


def test_bridge_client_error() -> None:
    server, thread = _start_server()
    host, port = server.server_address

    client = BlenderBridgeClient(
        BridgeConfig(host=host, port=int(port), token="secret", timeout_seconds=1.0)
    )

    with pytest.raises(BridgeError):
        client.call("fail")

    server.shutdown()
    server.server_close()
    thread.join(timeout=1.0)
