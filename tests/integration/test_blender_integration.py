from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from better_blender_mcp.bridge_client import BlenderBridgeClient
from better_blender_mcp.config import BridgeConfig

pytestmark = pytest.mark.integration


def _find_blender_executable() -> str | None:
    blender = shutil.which("blender")
    if blender:
        return blender

    candidates = [
        "/Applications/Blender.app/Contents/MacOS/Blender",
        os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
        "C:/Program Files/Blender Foundation/Blender/blender.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


@pytest.fixture
def bridge_client(tmp_path: Path):
    blender_exec = _find_blender_executable()
    if blender_exec is None:
        pytest.skip("Blender executable not available")

    repo_root = Path(__file__).resolve().parents[2]
    addon_parent = repo_root / "blender_addon"
    runner = repo_root / "tests" / "integration" / "run_bridge.py"

    port = _free_port()
    token = "integration-token"
    ready_file = tmp_path / "ready.flag"
    stop_file = tmp_path / "stop.flag"

    cmd = [
        blender_exec,
        "--background",
        "--factory-startup",
        "--python",
        str(runner),
        "--",
        "--addon-parent",
        str(addon_parent),
        "--port",
        str(port),
        "--token",
        token,
        "--ready-file",
        str(ready_file),
        "--stop-file",
        str(stop_file),
    ]

    process = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if ready_file.exists():
                break
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise RuntimeError(
                    "Blender bridge runner exited early.\n"
                    f"stdout:\n{stdout}\n"
                    f"stderr:\n{stderr}\n"
                )
            time.sleep(0.1)
        else:
            process.terminate()
            raise RuntimeError("Timed out waiting for Blender bridge to become ready")

        client = BlenderBridgeClient(
            BridgeConfig(host="127.0.0.1", port=port, token=token, timeout_seconds=10)
        )
        yield client
    finally:
        stop_file.touch()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_bridge_health_and_object_pipeline(bridge_client: BlenderBridgeClient) -> None:
    status = bridge_client.call("health")
    assert status["bridge_running"] is True

    scene = bridge_client.call("new_scene", {"use_empty": True})
    assert scene["objects_total"] == 0

    cube = bridge_client.call(
        "create_primitive",
        {"primitive": "CUBE", "name": "CubeA", "location": [1.0, 2.0, 3.0]},
    )
    assert cube["object"]["name"] == "CubeA"

    info = bridge_client.call("get_object_info", {"name": "CubeA"})
    assert info["object"]["location"] == [1.0, 2.0, 3.0]

    bridge_client.call("keyframe_transform", {"name": "CubeA", "frame": 1, "location": [0, 0, 0]})
    bridge_client.call("keyframe_transform", {"name": "CubeA", "frame": 10, "location": [2, 0, 0]})
    anim = bridge_client.call("list_animation_data", {"name": "CubeA"})
    assert anim["has_animation"] is True


def test_modifiers_collections_and_compositor(bridge_client: BlenderBridgeClient) -> None:
    bridge_client.call("new_scene", {"use_empty": True})
    bridge_client.call("create_primitive", {"primitive": "CUBE", "name": "CubeB"})

    modifier = bridge_client.call(
        "add_modifier",
        {
            "object_name": "CubeB",
            "modifier_type": "SUBSURF",
            "name": "SubsurfA",
            "settings": {"levels": 1},
        },
    )
    assert modifier["modifier"]["name"] == "SubsurfA"

    gn = bridge_client.call(
        "create_geometry_nodes_modifier",
        {"object_name": "CubeB", "modifier_name": "GeoNodesA"},
    )
    assert gn["modifier"]["type"] == "NODES"

    bridge_client.call("create_collection", {"name": "CollectionA"})
    bridge_client.call(
        "add_object_to_collection",
        {"object_name": "CubeB", "collection_name": "CollectionA"},
    )

    collections = bridge_client.call("list_collections")
    names = {item["name"] for item in collections["collections"]}
    assert "CollectionA" in names

    comp = bridge_client.call("enable_compositor", {"use_nodes": True, "clear_nodes": True})
    assert comp["use_nodes"] is True

    bridge_client.call("set_view_layer_passes", {"use_pass_z": True, "use_pass_normal": True})
