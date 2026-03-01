import pytest

from better_blender_mcp.protocol import BridgeRequest, BridgeResponse


def test_bridge_request_to_json():
    req = BridgeRequest(request_id="abc", method="health", params={"x": 1}, token="secret")

    assert req.to_json() == {
        "id": "abc",
        "method": "health",
        "params": {"x": 1},
        "token": "secret",
    }


def test_bridge_response_from_json_success():
    payload = {"id": "abc", "ok": True, "result": {"status": "ok"}}

    resp = BridgeResponse.from_json(payload)

    assert resp.request_id == "abc"
    assert resp.ok is True
    assert resp.result == {"status": "ok"}
    assert resp.error is None


def test_bridge_response_invalid_payload():
    with pytest.raises(ValueError):
        BridgeResponse.from_json({"ok": True})
