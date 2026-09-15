"""Keep every test's credentials and durable state isolated from the user's installation."""

import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("BETTER_BLENDER_STATE_DIR", str(tmp_path / "isolated-state"))
