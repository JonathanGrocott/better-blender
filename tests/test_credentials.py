import os
from concurrent.futures import ThreadPoolExecutor

from better_blender_mcp.config import load_config_from_env
from better_blender_mcp.credentials import ensure_token


def test_setup_generates_one_private_shared_token(tmp_path, monkeypatch):
    monkeypatch.setenv("BETTER_BLENDER_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("BETTER_BLENDER_TOKEN", raising=False)
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: ensure_token(), range(16)))
    assert len(set(tokens)) == 1
    assert len(tokens[0]) >= 32
    assert load_config_from_env().bridge.token == tokens[0]
    if os.name != "nt":
        assert (tmp_path / "token").stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".token-*"))
