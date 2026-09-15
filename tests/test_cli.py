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


def test_doctor_checks_bridge_compatibility(monkeypatch, capsys):
    import json

    monkeypatch.setattr(cli, "_find_blender_executable", lambda: Path("/test/blender"))
    monkeypatch.setattr(
        cli.BlenderBridgeClient,
        "call",
        lambda *a: {
            "protocol_version": 1,
            "blender_version": "5.0.1",
            "bridge_running": True,
            "capabilities": {
                "render_jobs": True,
                "inline_images": True,
                "strict_inputs": True,
                "checkpoints": True,
                "node_inspection": True,
                "persistent_jobs": True,
                "document_guards": True,
                "durable_requests": True,
                "access_controls": True,
                "checkpoint_retention": True,
                "diagnostics": True,
            },
        },
    )
    assert cli._run_doctor() == 0
    assert json.loads(capsys.readouterr().out)["bridge"]["compatible"] is True
    monkeypatch.setattr(
        cli.BlenderBridgeClient,
        "call",
        lambda *a: {
            "protocol_version": 99,
            "blender_version": "5.0.1",
        },
    )
    assert cli._run_doctor() == 1


def test_doctor_reports_connection_failure(monkeypatch, capsys):
    import json

    monkeypatch.setattr(cli, "_find_blender_executable", lambda: Path("/test/blender"))

    def offline(*args):
        raise ConnectionRefusedError("Bridge unavailable")

    monkeypatch.setattr(cli.BlenderBridgeClient, "call", offline)
    assert cli._run_doctor() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["bridge"]["connected"] is False
    assert "Bridge unavailable" in report["bridge"]["error"]


def test_doctor_detects_stale_addon(monkeypatch, capsys):
    import json

    monkeypatch.setattr(cli, "_find_blender_executable", lambda: Path("/test/blender"))
    monkeypatch.setattr(
        cli.BlenderBridgeClient,
        "call",
        lambda *a: {
            "protocol_version": 1,
            "blender_version": "5.0.1",
            "bridge_running": True,
        },
    )
    assert cli._run_doctor() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["bridge"]["missing_capabilities"] == [
        "access_controls",
        "checkpoint_retention",
        "checkpoints",
        "diagnostics",
        "document_guards",
        "durable_requests",
        "inline_images",
        "node_inspection",
        "persistent_jobs",
        "render_jobs",
        "strict_inputs",
    ]


def test_install_failure_restores_previous_addon(tmp_path, monkeypatch):
    target = tmp_path / "better_blender_bridge"
    target.mkdir()
    (target / "previous.txt").write_text("previous version")
    rename = Path.rename

    def fail_activation(self, destination):
        if self.name == "incoming":
            raise OSError("simulated activation failure")
        return rename(self, destination)

    monkeypatch.setattr(Path, "rename", fail_activation)
    assert cli._install_addon("5.0", str(tmp_path)) == 1
    assert (target / "previous.txt").read_text() == "previous version"
    assert not list(tmp_path.glob(".better-blender-install-*"))


def test_copy_failure_leaves_installed_addon_intact(tmp_path, monkeypatch):
    target = tmp_path / "better_blender_bridge"
    target.mkdir()
    (target / "previous.txt").write_text("previous version")

    def fail_copy(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(cli.shutil, "copytree", fail_copy)
    assert cli._install_addon("5.0", str(tmp_path)) == 1
    assert (target / "previous.txt").exists()
