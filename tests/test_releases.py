import hashlib
import importlib
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

VERSION = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())[
    "project"
]["version"]


@pytest.fixture
def release_tools(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("check_release"), importlib.import_module("publish_release")


@pytest.fixture
def assets(tmp_path):
    directory = tmp_path / "assets"
    directory.mkdir()
    for name in (
        f"better_blender_mcp-{VERSION}-py3-none-any.whl",
        f"better_blender_bridge-{VERSION}.zip",
    ):
        with zipfile.ZipFile(directory / name, "w") as archive:
            archive.writestr("better_blender_bridge/__init__.py", "bridge contents")
    (directory / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
            for file in sorted(directory.iterdir())
        )
    )
    return directory


def test_release_tag_and_corruption_are_rejected(release_tools, assets):
    validator, _ = release_tools
    assert validator.check_version(tag=f"v{VERSION}") == VERSION
    with pytest.raises(ValueError, match="does not match"):
        validator.check_version(tag="v9.9.9")
    assert len(validator.check_assets(assets, VERSION)) == 3
    (assets / f"better_blender_bridge-{VERSION}.zip").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        validator.check_assets(assets, VERSION)


@pytest.mark.parametrize("corrupt_download", [False, True])
def test_draft_is_published_only_after_download_verification(
    release_tools,
    assets,
    monkeypatch,
    corrupt_download,
):
    _, publisher = release_tools
    calls = []

    def gh(command, **kwargs):
        calls.append(command)
        if command[2] == "view":
            return subprocess.CompletedProcess(command, 0, '{"isDraft": true}', "")
        if command[2] == "download":
            destination = Path(command[-1])
            for file in assets.iterdir():
                shutil.copy2(file, destination / file.name)
            if corrupt_download:
                (destination / "SHA256SUMS").write_text("")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(publisher.subprocess, "run", gh)
    if corrupt_download:
        with pytest.raises(ValueError, match="Missing checksum"):
            publisher.publish(f"v{VERSION}", assets)
        assert not any(command[2] == "edit" for command in calls)
    else:
        publisher.publish(f"v{VERSION}", assets)
        assert calls[-1] == ["gh", "release", "edit", f"v{VERSION}", "--draft=false"]


def test_public_release_is_never_overwritten(release_tools, assets, monkeypatch):
    _, publisher = release_tools
    calls = []

    def gh(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '{"isDraft": false}', "")

    monkeypatch.setattr(publisher.subprocess, "run", gh)
    publisher.publish(f"v{VERSION}", assets)
    assert len(calls) == 1 and calls[0][2] == "view"
