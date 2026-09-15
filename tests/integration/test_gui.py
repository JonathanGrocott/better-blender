import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.gui]


def test_real_gui_addon_lifecycle(tmp_path):
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("Run with xvfb-run to exercise the real Blender UI")
    blender = shutil.which("blender")
    if blender is None:
        mac = Path("/Applications/Blender.app/Contents/MacOS/Blender")
        if not mac.exists():
            pytest.skip("Blender unavailable")
        blender = str(mac)
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            blender,
            "--factory-startup",
            "--python",
            str(Path(__file__).with_name("gui_lifecycle.py")),
            "--",
            str(root / "blender_addon"),
            str(tmp_path),
        ],
        env={
            **os.environ,
            "BETTER_BLENDER_STATE_DIR": str(tmp_path / "state"),
            "BLENDER_USER_CONFIG": str(tmp_path / "config"),
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    report = tmp_path / "result.json"
    assert report.exists(), result.stdout + result.stderr
    data = json.loads(report.read_text())
    assert data.get("ok") and not data.get("error"), data
    assert result.returncode == 0, result.stdout + result.stderr
