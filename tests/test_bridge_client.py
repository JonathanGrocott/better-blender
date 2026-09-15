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


def test_buffered_reader_rejects_truncated_and_oversized_messages(monkeypatch):
    import socket

    import better_blender_mcp.bridge_client as module

    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 32)
    for data, expected in [(b'{"ok":true}', "INVALID_MESSAGE"), (b"x" * 33, "RESPONSE_TOO_LARGE")]:
        left, right = socket.socketpair()
        with left, right:
            right.sendall(data)
            right.shutdown(socket.SHUT_WR)
            with pytest.raises(BridgeError) as exc:
                BlenderBridgeClient._read_line(left)
            assert exc.value.code == expected


def test_buffered_reader_handles_fragmented_utf8():
    import socket

    left, right = socket.socketpair()
    with left, right:
        data = '{"value":"é"}\n'.encode()

        def send():
            for byte in data:
                right.sendall(bytes([byte]))

        sender = threading.Thread(target=send)
        sender.start()
        assert BlenderBridgeClient._read_line(left) == '{"value":"é"}'
        sender.join()


def test_transport_failure_exposes_request_id(monkeypatch):
    import socket

    def fail_connection(*args, **kwargs):
        raise OSError("connection lost")

    monkeypatch.setattr(socket, "create_connection", fail_connection)
    with pytest.raises(BridgeError) as error:
        BlenderBridgeClient(BridgeConfig()).call("create_collection", {"name": "Example"})
    assert error.value.request_id
    assert error.value.request_id in str(error.value)
