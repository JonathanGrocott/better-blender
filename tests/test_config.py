from better_blender_mcp.config import load_config_from_env


def test_load_config_defaults(monkeypatch):
    monkeypatch.delenv("BETTER_BLENDER_HOST", raising=False)
    monkeypatch.delenv("BETTER_BLENDER_PORT", raising=False)
    monkeypatch.delenv("BETTER_BLENDER_TOKEN", raising=False)
    monkeypatch.delenv("BETTER_BLENDER_TIMEOUT", raising=False)

    cfg = load_config_from_env()

    assert cfg.bridge.host == "127.0.0.1"
    assert cfg.bridge.port == 8765
    assert cfg.bridge.token == "change-me"
    assert cfg.bridge.timeout_seconds == 30.0


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("BETTER_BLENDER_HOST", "localhost")
    monkeypatch.setenv("BETTER_BLENDER_PORT", "9999")
    monkeypatch.setenv("BETTER_BLENDER_TOKEN", "secret")
    monkeypatch.setenv("BETTER_BLENDER_TIMEOUT", "15")

    cfg = load_config_from_env()

    assert cfg.bridge.host == "localhost"
    assert cfg.bridge.port == 9999
    assert cfg.bridge.token == "secret"
    assert cfg.bridge.timeout_seconds == 15.0
