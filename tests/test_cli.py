from __future__ import annotations

from pathlib import Path

from better_blender_mcp import cli


def test_normalize_blender_scripts_version_accepts_patch() -> None:
    assert cli._normalize_blender_scripts_version("3.4.1") == "3.4"
    assert cli._normalize_blender_scripts_version("4.2") == "4.2"


def test_normalize_blender_scripts_version_rejects_invalid() -> None:
    try:
        cli._normalize_blender_scripts_version("3")
    except ValueError as exc:
        assert "major.minor" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid Blender version")


def test_install_addon_accepts_patch_version(tmp_path: Path) -> None:
    destination = tmp_path / "addons"
    result = cli._install_addon("3.4.1", str(destination))

    assert result == 0
    assert (destination / "better_blender_bridge" / "__init__.py").exists()

