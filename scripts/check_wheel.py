"""Build and exercise installation outside the checkout, without importing bpy."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="bb-wheel-") as work:
    work = Path(work)
    source = work / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "src", "blender_addon"):
        src, dest = root / name, source / name
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        else:
            shutil.copy2(src, dest)
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", str(source), "-w", str(work)],
        check=True,
    )
    wheel = next(work.glob("*.whl"))
    installed = work / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(installed),
            str(wheel),
        ],
        check=True,
    )
    env = {**os.environ, "PYTHONPATH": str(installed)}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "better_blender_mcp.cli",
            "install-addon",
            "--blender-version",
            "3.4.1",
            "--destination",
            str(work / "addons"),
        ],
        cwd=work,
        env=env,
        check=True,
    )
    addon = work / "addons/better_blender_bridge"
    for name in ("__init__.py", "validation.py", "schemas.json"):
        assert (addon / name).exists(), name
    print("Wheel install and add-on extraction passed")
