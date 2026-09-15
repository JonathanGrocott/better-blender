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


def test_bridge_request_includes_optional_execution_budget():
    req = BridgeRequest(
        request_id="abc",
        method="health",
        params={},
        token="secret",
        timeout_seconds=0.5,
    )
    assert req.to_json()["timeout_seconds"] == 0.5


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"id": "a", "ok": True},
        {"id": "a", "ok": True, "result": []},
        {"id": "a", "ok": False},
        {"id": "a", "ok": False, "error": "bad", "code": 1},
    ],
)
def test_rejects_malformed_response_envelopes(payload):
    with pytest.raises(ValueError):
        BridgeResponse.from_json(payload)
