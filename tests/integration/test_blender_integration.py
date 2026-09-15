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
        "--timeout-seconds",
        "60",
    ]

    process = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "BETTER_BLENDER_STATE_DIR": str(tmp_path / "state")},
    )

    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if ready_file.exists():
                break
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise RuntimeError(
                    f"Blender bridge runner exited early.\nstdout:\n{stdout}\nstderr:\n{stderr}\n"
                )
            time.sleep(0.1)
        else:
            process.terminate()
            raise RuntimeError("Timed out waiting for Blender bridge to become ready")

        client = BlenderBridgeClient(
            BridgeConfig(host="127.0.0.1", port=port, token=token, timeout_seconds=60)
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

    actions = bridge_client.call("list_actions")
    assert actions["count"] >= 1

    duplicate = bridge_client.call(
        "duplicate_action",
        {"action_name": anim["action"], "new_name": "CubeA_Action_Copy"},
    )
    assert duplicate["action"]["name"] == "CubeA_Action_Copy"

    strip = bridge_client.call(
        "create_nla_strip",
        {
            "object_name": "CubeA",
            "action_name": "CubeA_Action_Copy",
            "track_name": "TrackA",
            "strip_name": "StripA",
            "frame_start": 1,
        },
    )
    assert strip["strip"]["name"] == "StripA"

    updated = bridge_client.call(
        "set_nla_strip",
        {
            "object_name": "CubeA",
            "track_name": "TrackA",
            "strip_name": "StripA",
            "scale": 1.5,
            "repeat": 2.0,
        },
    )
    assert updated["strip"]["scale"] == 1.5
    assert updated["strip"]["repeat"] == 2.0

    tracks = bridge_client.call("list_nla_tracks", {"object_name": "CubeA"})
    assert tracks["count"] >= 1

    removed = bridge_client.call(
        "remove_nla_strip",
        {"object_name": "CubeA", "track_name": "TrackA", "strip_name": "StripA"},
    )
    assert removed["removed_strip"] == "StripA"


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

    geom_input = bridge_client.call(
        "add_geometry_input",
        {
            "object_name": "CubeB",
            "modifier_name": "GeoNodesA",
            "input_name": "ScaleInput",
            "socket_type": "NodeSocketFloat",
            "default_value": 1.0,
        },
    )
    identifier = geom_input["input"]["identifier"]

    bridge_client.call(
        "set_geometry_input",
        {
            "object_name": "CubeB",
            "modifier_name": "GeoNodesA",
            "input_name_or_identifier": identifier,
            "value": 2.5,
        },
    )
    inputs = bridge_client.call(
        "list_geometry_inputs",
        {"object_name": "CubeB", "modifier_name": "GeoNodesA"},
    )
    by_id = {item["identifier"]: item for item in inputs["inputs"]}
    assert by_id[identifier]["value"] == 2.5

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


def test_high_level_workflow_turntable_render(
    bridge_client: BlenderBridgeClient,
    tmp_path: Path,
) -> None:
    bridge_client.call("new_scene", {"use_empty": True})

    render_dir = tmp_path / "turntable"
    output_prefix = render_dir / "frame_"

    result = bridge_client.call(
        "workflow_turntable_render",
        {
            "output_path": str(output_prefix),
            "object_name": "WorkflowSubject",
            "frame_start": 1,
            "frame_end": 3,
            "rotations": 0.5,
            "axis": "Z",
            "setup_studio": True,
            "primitive": "CUBE",
            "size": 1.5,
            "add_ground": True,
            "engine": "BLENDER_WORKBENCH",
            "resolution_x": 64,
            "resolution_y": 64,
        },
    )
    assert result["rendered"] is True
    assert result["object_name"] == "WorkflowSubject"

    rendered_files = list(render_dir.glob("frame_*"))
    assert rendered_files, "Expected rendered animation frames to exist"


def test_capture_viewport_screenshot_headless_fallback(
    bridge_client: BlenderBridgeClient,
    tmp_path: Path,
) -> None:
    bridge_client.call("new_scene", {"use_empty": True})
    bridge_client.call(
        "workflow_setup_studio",
        {"object_name": "CaptureSubject", "primitive": "CUBE", "size": 1.0},
    )

    capture_path = tmp_path / "viewport_capture.png"
    result = bridge_client.call(
        "capture_viewport_screenshot",
        {
            "filepath": str(capture_path),
            "fallback_to_render": True,
            "engine": "BLENDER_WORKBENCH",
            "resolution_x": 64,
            "resolution_y": 64,
        },
    )
    assert result["captured"] is True
    assert result["capture_mode"] in {"viewport_opengl", "render_fallback_no_viewport"}
    assert capture_path.exists()


def test_delete_object_returns_success(bridge_client: BlenderBridgeClient) -> None:
    bridge_client.call("create_primitive", {"name": "DeleteMe"})
    assert bridge_client.call("delete_object", {"name": "DeleteMe"}) == {"deleted": "DeleteMe"}
    assert "DeleteMe" not in {obj["name"] for obj in bridge_client.call("list_objects")["objects"]}


def test_geometry_edits_preserve_existing_output(bridge_client: BlenderBridgeClient) -> None:
    bridge_client.call("create_primitive", {"name": "GraphSubject"})
    params = {"object_name": "GraphSubject"}
    bridge_client.call("create_geometry_nodes_modifier", params)
    bridge_client.call(
        "add_geometry_node",
        {
            **params,
            "node_type": "GeometryNodeTransform",
            "node_name": "Transform",
        },
    )
    bridge_client.call(
        "link_geometry_nodes",
        {
            **params,
            "from_node": "Group Input",
            "from_socket": "Geometry",
            "to_node": "Transform",
            "to_socket": "Geometry",
        },
    )
    bridge_client.call(
        "link_geometry_nodes",
        {
            **params,
            "from_node": "Transform",
            "from_socket": "Geometry",
            "to_node": "Group Output",
            "to_socket": "Geometry",
        },
    )
    before = bridge_client.call("list_geometry_nodes", params)["links"]
    bridge_client.call("add_geometry_node", {**params, "node_type": "ShaderNodeMath"})
    bridge_client.call("create_geometry_nodes_modifier", params)
    assert bridge_client.call("list_geometry_nodes", params)["links"] == before
    assert any(link["from_node"] == "Transform" for link in before)


def test_object_operations_reject_edit_mode() -> None:
    blender = _find_blender_executable()
    if blender is None:
        pytest.skip("Blender executable not available")
    addon_parent = Path(__file__).resolve().parents[2] / "blender_addon"
    code = (
        f"import sys; sys.path.insert(0, {str(addon_parent)!r})\n"
        + """
import bpy
import better_blender_bridge as bridge
obj = bpy.context.active_object
name = obj.name
modifier = obj.modifiers.new(name='TestModifier', type='SUBSURF')
bpy.ops.object.mode_set(mode='EDIT')
for method, params in [
    ('create_primitive', {'name': 'MustNotExist'}),
    ('duplicate_object', {'name': name}),
    ('apply_modifier', {'object_name': name, 'modifier_name': modifier.name}),
]:
    try:
        bridge._dispatch_command(method, params)
    except ValueError as exc:
        assert 'Object Mode' in str(exc)
    else:
        raise AssertionError(method + ' unexpectedly succeeded')
assert bpy.context.mode == 'EDIT_MESH'
assert obj.name == name
assert len(bpy.context.scene.objects) == 3
assert len(obj.modifiers) == 1
bpy.ops.object.mode_set(mode='OBJECT')
assert len(obj.data.vertices) == 8
"""
    )
    result = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_expired_commands_never_execute_and_running_timeout_is_explicit() -> None:
    blender = _find_blender_executable()
    if blender is None:
        pytest.skip("Blender executable not available")
    addon_parent = Path(__file__).resolve().parents[2] / "blender_addon"
    code = (
        f"import sys; sys.path.insert(0, {str(addon_parent)!r})\n"
        + r"""
import json
import socket
import threading
import time
import bpy
import better_blender_bridge as bridge
bridge.start_bridge_with_config('127.0.0.1', 0, 'test', register_timer=False)
runtime = bridge._RUNTIME
port = runtime.server.server_address[1]
def request(method, params):
    with socket.create_connection(('127.0.0.1', port), timeout=2) as sock:
        sock.sendall((json.dumps({
            'id': method + str(time.monotonic()), 'method': method, 'params': params,
            'token': 'test', 'timeout_seconds': 0.05,
        }) + '\n').encode())
        with sock.makefile('rb') as stream:
            return json.loads(stream.readline())
try:
    response = request('create_collection', {'name': 'MustNotExist'})
    assert response['code'] == 'EXPIRED', response
    bridge._drain_command_queue()
    assert bpy.data.collections.get('MustNotExist') is None

    original = bridge._dispatch_command
    execution_threads = []
    def slow_dispatch(method, params):
        execution_threads.append(threading.get_ident())
        time.sleep(0.15)
        return original(method, params)
    bridge._dispatch_command = slow_dispatch
    responses = []
    worker = threading.Thread(target=lambda: responses.append(
        request('create_collection', {'name': 'RunningOperation'})
    ))
    worker.start()
    deadline = time.monotonic() + 2
    while runtime.command_queue.empty():
        assert time.monotonic() < deadline
        time.sleep(0.001)
    bridge._drain_command_queue()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert responses[0]['code'] == 'OUTCOME_UNKNOWN', responses
    assert bpy.data.collections.get('RunningOperation') is not None
    assert execution_threads == [threading.get_ident()]
finally:
    bridge.stop_bridge()
"""
    )
    result = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_requests_leave_scene_unchanged(bridge_client: BlenderBridgeClient) -> None:
    from better_blender_mcp.bridge_client import BridgeError

    bridge_client.call("create_primitive", {"name": "Validated"})
    before = bridge_client.call("get_object_info", {"name": "Validated"})
    for params in [
        {"name": "Validated", "location": [9, 8, 7], "scale": [1]},
        {"name": "Validated", "location": [9, 8, 7], "typo": True},
    ]:
        with pytest.raises(BridgeError):
            bridge_client.call("set_object_transform", params)
        assert bridge_client.call("get_object_info", {"name": "Validated"}) == before
    with pytest.raises(BridgeError):
        bridge_client.call(
            "add_modifier",
            {
                "object_name": "Validated",
                "modifier_type": "SUBSURF",
                "settings": {"levels": 2, "misspelled": 1},
            },
        )
    assert bridge_client.call("list_modifiers", {"object_name": "Validated"})["count"] == 0
    with pytest.raises(BridgeError):
        bridge_client.call("create_collection", {"name": "Orphan", "parent_name": "Missing"})
    collections = bridge_client.call("list_collections")["collections"]
    assert "Orphan" not in {c["name"] for c in collections}


def test_bridge_rejects_malformed_envelopes(bridge_client: BlenderBridgeClient):
    import json

    for raw in (b"[]\n", b"null\n", b"\xff\n"):
        with socket.create_connection(
            (bridge_client.config.host, bridge_client.config.port)
        ) as conn:
            conn.sendall(raw)
            response = json.loads(conn.makefile("rb").readline())
            assert response["ok"] is False
            assert response["code"] == "INVALID_REQUEST"
    assert bridge_client.call("health")["bridge_running"] is True


def test_render_job_completion_and_cancellation(bridge_client: BlenderBridgeClient, tmp_path: Path):
    bridge_client.call("workflow_setup_studio", {"object_name": "JobSubject"})
    before = bridge_client.call("get_scene_info")
    output = tmp_path / "job.png"
    job = bridge_client.call(
        "start_render_job",
        {
            "method": "render_still",
            "params": {
                "filepath": str(output),
                "engine": "BLENDER_WORKBENCH",
                "resolution_x": 64,
                "resolution_y": 64,
            },
        },
    )

    def wait_terminal(job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = bridge_client.call("get_job_status", {"job_id": job_id})
            if state["state"] not in {"running", "cancelling"}:
                return state
            time.sleep(0.05)
        raise AssertionError("Job did not finish")

    completed = wait_terminal(job["job_id"])
    assert completed["state"] == "completed", completed
    assert completed["result"]["rendered"] is True
    assert completed["progress"]["fraction"] == 1.0
    assert completed["result"]["outputs"] == [str(output)]
    assert bridge_client.call("list_jobs")["total"] == 1
    assert (
        bridge_client.call("get_job_image", {"job_id": job["job_id"]})["image"]["mime_type"]
        == "image/png"
    )
    assert output.exists()
    assert bridge_client.call("get_scene_info") == before
    job = bridge_client.call(
        "start_render_job",
        {
            "method": "render_animation",
            "params": {
                "filepath": str(tmp_path / "long_"),
                "engine": "BLENDER_WORKBENCH",
                "frame_start": 1,
                "frame_end": 10000,
            },
        },
    )
    bridge_client.call("cancel_job", {"job_id": job["job_id"]})
    assert wait_terminal(job["job_id"])["state"] == "cancelled"
    assert bridge_client.call("health")["bridge_running"] is True


def test_mcp_stdio_handshake_validation_and_image(
    bridge_client: BlenderBridgeClient, tmp_path: Path
):
    import asyncio
    import base64
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    bridge_client.call("workflow_setup_studio", {"object_name": "McpSubject"})

    async def check():
        config = bridge_client.config
        server = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "better_blender_mcp.cli",
                "serve",
            ],
            env={
                **os.environ,
                "BETTER_BLENDER_HOST": config.host,
                "BETTER_BLENDER_PORT": str(config.port),
                "BETTER_BLENDER_TOKEN": config.token,
            },
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert any(t.name == "cancel_job" for t in tools.tools)
                health = await session.call_tool("get_blender_status", {})
                assert not health.isError
                invalid = await session.call_tool(
                    "set_object_transform",
                    {
                        "name": "McpSubject",
                        "location": [1, 2],
                    },
                )
                assert invalid.isError
                capture = await session.call_tool(
                    "capture_viewport_screenshot",
                    {
                        "filepath": str(tmp_path / "mcp.png"),
                        "engine": "BLENDER_WORKBENCH",
                        "resolution_x": 64,
                        "resolution_y": 64,
                    },
                )
                assert not capture.isError, capture
                image = next(c for c in capture.content if c.type == "image")
                assert image.mimeType == "image/png"
                assert base64.b64decode(image.data).startswith(b"\x89PNG\r\n\x1a\n")
                job = await session.call_tool(
                    "render_still",
                    {
                        "filepath": str(tmp_path / "mcp-job.png"),
                        "engine": "BLENDER_WORKBENCH",
                        "resolution_x": 64,
                        "resolution_y": 64,
                    },
                )
                assert not job.isError
                assert job.structuredContent["job_id"]
                await session.call_tool("cancel_job", {"job_id": job.structuredContent["job_id"]})

    asyncio.run(check())


def test_glb_export_import_roundtrip(bridge_client: BlenderBridgeClient, tmp_path: Path):
    bridge_client.call("new_scene", {"use_empty": True})
    bridge_client.call("create_primitive", {"name": "RoundTrip"})
    path = tmp_path / "scene.glb"
    result = bridge_client.call("export_file", {"filepath": str(path)})
    assert result["filepath"] == str(path)
    assert path.read_bytes()[:4] == b"glTF"
    bridge_client.call("new_scene", {"use_empty": True})
    assert bridge_client.call("import_file", {"filepath": str(path)})["objects_total"] == 1


def test_transport_capacity_and_read_deadline():
    blender = _find_blender_executable()
    if blender is None:
        pytest.skip("Blender executable not available")
    addon_parent = Path(__file__).resolve().parents[2] / "blender_addon"
    code = (
        f"import sys; sys.path.insert(0, {str(addon_parent)!r})\n"
        + r"""
import json
import socket
import time
import better_blender_bridge as bridge
bridge.MAX_CONNECTIONS = 2
bridge.MAX_QUEUED_COMMANDS = 1
bridge.READ_TIMEOUT = 2
bridge.start_bridge_with_config('127.0.0.1', 0, 'test', register_timer=False)
runtime = bridge._RUNTIME
endpoint = runtime.server.server_address
def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.001)
def read(sock):
    with sock.makefile('rb') as stream:
        return json.loads(stream.readline())
try:
    with socket.create_connection(endpoint) as a, socket.create_connection(endpoint) as b:
        wait_for(lambda: runtime.server.slots._value == 0)
        with socket.create_connection(endpoint) as excess:
            assert read(excess)['code'] == 'BUSY'
    wait_for(lambda: runtime.server.slots._value == 2)
    payload = json.dumps({'id':'a', 'method':'health', 'token':'test',
                          'timeout_seconds':.5}).encode() + b'\n'
    with socket.create_connection(endpoint) as a:
        a.sendall(payload)
        wait_for(lambda: runtime.command_queue.qsize() == 1)
        with socket.create_connection(endpoint) as b:
            b.sendall(payload)
            assert read(b)['code'] == 'BUSY'
        assert read(a)['code'] == 'EXPIRED'
    bridge._drain_command_queue()
    wait_for(lambda: runtime.server.slots._value == 2)
    bridge.READ_TIMEOUT = .05
    with socket.create_connection(endpoint) as slow:
        slow.sendall(b'{')
        assert read(slow)['code'] == 'INVALID_REQUEST'
finally:
    bridge.stop_bridge()
"""
    )
    result = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_checkpoint_restores_scene_after_partial_work(bridge_client: BlenderBridgeClient):
    from better_blender_mcp.bridge_client import BridgeError

    bridge_client.call("new_scene", {"use_empty": True})
    bridge_client.call("create_primitive", {"name": "Recoverable"})
    original_path = bridge_client.call("get_scene_info")["file_path"]
    saved = bridge_client.call("create_checkpoint", {"label": "Before edits"})
    assert bridge_client.call("get_scene_info")["file_path"] == original_path
    bridge_client.call("set_object_transform", {"name": "Recoverable", "location": [3, 2, 1]})
    with pytest.raises(BridgeError):
        bridge_client.call(
            "add_modifier",
            {
                "object_name": "Recoverable",
                "modifier_type": "INVALID",
            },
        )
    restored = bridge_client.call("restore_checkpoint", {"checkpoint_id": saved["checkpoint_id"]})
    assert restored["recovery_checkpoint"]
    assert restored["filepath"] != saved["filepath"]
    assert bridge_client.call("get_object_info", {"name": "Recoverable"})["object"]["location"] == [
        0,
        0,
        0,
    ]
    deleted = bridge_client.call(
        "run_with_checkpoint",
        {
            "method": "delete_object",
            "params": {"name": "Recoverable"},
        },
    )
    assert deleted["result"]["deleted"] == "Recoverable"
    assert bridge_client.call("list_checkpoints")["total"] == 3


def test_scene_and_node_inspection(bridge_client: BlenderBridgeClient):
    for name in ("InspectA", "InspectB", "InspectC"):
        bridge_client.call("create_primitive", {"name": name, "location": [2, 0, 0]})
    page = bridge_client.call("list_objects", {"query": "Inspect", "limit": 2})
    assert page["total"] == 3 and page["next_offset"] == 2
    assert [obj["name"] for obj in page["objects"]] == ["InspectA", "InspectB"]
    assert bridge_client.call("list_objects", {"query": "Inspect", "offset": 2})["count"] == 1
    obj = bridge_client.call("get_object_info", {"name": "InspectA", "evaluated": True})["object"]
    assert obj["matrix_world"][0][3] == 2
    assert obj["evaluated_world_bounds"]["min"] == [1, -1, -1]
    assert obj["collections"] and obj["visible"]
    bridge_client.call("create_geometry_nodes_modifier", {"object_name": "InspectA"})
    node = bridge_client.call(
        "get_node_info",
        {
            "object_name": "InspectA",
            "node_name": "Group Input",
        },
    )
    assert any(socket["name"] == "Geometry" for socket in node["outputs"])
    assert any(prop["name"] == "label" for prop in node["properties"])


def test_document_guard_and_idempotent_edits(bridge_client):
    from better_blender_mcp.bridge_client import BridgeError

    context = bridge_client.call("get_document_context")
    params = {
        "request_id": "stable-create-id",
        "expected_document_id": context["document_id"],
        "method": "create_collection",
        "params": {"name": "OnlyOnce"},
    }
    first = bridge_client.call("execute_request", params)
    assert bridge_client.call("execute_request", params) == first
    status = bridge_client.call("get_request_status", {"request_id": "stable-create-id"})
    assert status["state"] == "completed"
    bridge_client.call("new_scene", {"use_empty": True})
    with pytest.raises(BridgeError, match="changed"):
        bridge_client.call("execute_request", {**params, "request_id": "stale-document"})
    # A completed retry remains a replay even after a document switch.
    assert bridge_client.call("execute_request", params) == first
    names = [item["name"] for item in bridge_client.call("list_collections")["collections"]]
    assert "OnlyOnce" not in names


def test_access_controls_and_shutdown_release_queued_calls(tmp_path):
    blender = _find_blender_executable()
    if blender is None:
        pytest.skip("Blender executable not available")
    addon_parent = Path(__file__).resolve().parents[2] / "blender_addon"
    code = (
        f"import sys; sys.path.insert(0, {str(addon_parent)!r})\n"
        + r"""
import json, socket, threading, time
from pathlib import Path
import bpy
import better_blender_bridge as bridge
try:
    bridge.start_bridge_with_config('0.0.0.0', 0, 'test', register_timer=False)
    raise AssertionError('Nonlocal binding accepted')
except ValueError as exc:
    assert 'opt-in' in str(exc)
root = Path(__import__('os').environ['BETTER_BLENDER_STATE_DIR'])
root.mkdir(parents=True, exist_ok=True)
bridge.start_bridge_with_config('127.0.0.1', 0, 'test', read_only=True,
    allowed_roots=(str(root),), register_timer=False)
try:
    bridge._dispatch_command('get_scene_info', {})
    try:
        bridge._dispatch_command('create_collection', {'name': 'Forbidden'})
        raise AssertionError('Read-only mutation accepted')
    except ValueError as exc:
        assert 'read-only' in str(exc)
    assert bpy.data.collections.get('Forbidden') is None
    bridge._RUNTIME.read_only = False
    for path in [root / '..' / 'escape.blend']:
        try:
            bridge._dispatch_command('save_blend', {'filepath': str(path)})
            raise AssertionError('Path escape accepted')
        except ValueError as exc:
            assert 'outside' in str(exc)
    try:
        bridge._dispatch_command('start_render_job', {'method': 'workflow_turntable_render',
            'params': {'output_path': str(root.parent / 'outside')}})
        raise AssertionError('Worker output path escape accepted')
    except ValueError as exc:
        assert 'outside' in str(exc), str(exc)
    image = bpy.data.images.new('Missing external image', width=1, height=1)
    image.source = 'FILE'
    image.filepath = str(root / 'missing.png')
    try:
        bridge._dispatch_command('start_render_job', {'method': 'render_still',
            'params': {'filepath': str(root / 'output.png')}})
        raise AssertionError('Missing render assets accepted')
    except ValueError as exc:
        assert 'Missing external assets' in str(exc), str(exc)
    assert bridge._RUNTIME.render_jobs.list_jobs()['total'] == 0
    bpy.data.images.remove(image)
    link = root / 'link'
    link.symlink_to(root.parent, target_is_directory=True)
    try:
        bridge._normalize_path(str(link / 'escape.blend'), require_exists=False)
        raise AssertionError('Symlink escape accepted')
    except ValueError:
        pass
    runtime = bridge._RUNTIME
    responses = []
    def request():
        with socket.create_connection(('127.0.0.1', runtime.server.server_address[1])) as sock:
            sock.sendall((json.dumps({'id': 'shutdown', 'method': 'create_collection',
                'params': {'name': 'Never'}, 'token': 'test'}) + '\n').encode())
            responses.append(json.loads(sock.makefile('rb').readline()))
    worker = threading.Thread(target=request)
    worker.start()
    deadline = time.monotonic() + 3
    while runtime.command_queue.empty():
        assert time.monotonic() < deadline
        time.sleep(.001)
    bridge.stop_bridge()
    worker.join(2)
    assert not worker.is_alive()
    assert responses[0]['code'] == 'EXPIRED'
    assert bpy.data.collections.get('Never') is None
finally:
    bridge.stop_bridge()
"""
    )
    result = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "BETTER_BLENDER_STATE_DIR": str(tmp_path / "state")},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_checkpoint_retention_preserves_working_copies(bridge_client, tmp_path):
    bridge_client.call("new_scene", {"use_empty": True})
    first = bridge_client.call("create_checkpoint", {"label": "First"})
    restored = bridge_client.call(
        "restore_checkpoint",
        {
            "checkpoint_id": first["checkpoint_id"],
            "backup_current": False,
        },
    )
    working = Path(restored["filepath"])
    assert working.exists()
    deleted = bridge_client.call("delete_checkpoint", {"checkpoint_id": first["checkpoint_id"]})
    assert str(working) in deleted["retained_files"]
    assert working.exists()
    bridge_client.call("configure_checkpoint_retention", {"max_count": 1, "max_bytes": 100000000})
    old = bridge_client.call("create_checkpoint", {"label": "Old"})
    newest = bridge_client.call("create_checkpoint", {"label": "Newest"})
    assert not Path(old["filepath"]).exists()
    assert Path(newest["filepath"]).exists()
    usage = bridge_client.call("get_checkpoint_usage")
    assert usage["count"] == 1 and usage["within_limits"]
    assert usage["other_bytes"] >= working.stat().st_size
    # Metadata captures the external paths at creation, checked afresh before restore.
    import json

    metadata_path = Path(newest["filepath"]).with_name("metadata.json")
    metadata = json.loads(metadata_path.read_text())
    missing = str(tmp_path / "missing-texture.png")
    metadata["external_assets"] = [missing]
    metadata_path.write_text(json.dumps(metadata))
    report = bridge_client.call("check_assets", {"checkpoint_id": newest["checkpoint_id"]})
    assert report["missing"] == [missing]
    from better_blender_mcp.bridge_client import BridgeError

    with pytest.raises(BridgeError, match="assets are missing"):
        bridge_client.call("restore_checkpoint", {"checkpoint_id": newest["checkpoint_id"]})
    assert bridge_client.call("get_scene_info")["file_path"] == str(working)


def test_disconnected_retry_and_queued_document_switch(tmp_path):
    blender = _find_blender_executable()
    if blender is None:
        pytest.skip("Blender executable not available")
    addon_parent = Path(__file__).resolve().parents[2] / "blender_addon"
    code = (
        f"import sys; sys.path.insert(0, {str(addon_parent)!r})\n"
        + r"""
import json, socket, threading, time
import bpy
import better_blender_bridge as bridge
bridge.start_bridge_with_config('127.0.0.1', 0, 'test', register_timer=False)
runtime = bridge._RUNTIME
port = runtime.server.server_address[1]
def send(identifier, method, params):
    sock = socket.create_connection(('127.0.0.1', port), timeout=3)
    sock.sendall((json.dumps({'id': identifier, 'method': method, 'params': params,
                             'token': 'test'}) + '\n').encode())
    return sock
def wait_depth(depth):
    deadline = time.monotonic() + 3
    while runtime.command_queue.qsize() < depth:
        assert time.monotonic() < deadline
        time.sleep(.001)
def receive(sock):
    with sock:
        return json.loads(sock.makefile('rb').readline())
try:
    disconnected = send('lost-response', 'create_collection', {'name': 'OnlyOnce'})
    wait_depth(1)
    disconnected.close()
    duplicate = receive(send('lost-response', 'create_collection', {'name': 'OnlyOnce'}))
    assert duplicate['code'] == 'OUTCOME_UNKNOWN'
    bridge._drain_command_queue()
    replay = receive(send('lost-response', 'create_collection', {'name': 'OnlyOnce'}))
    assert replay['ok'], replay
    assert bpy.data.collections.get('OnlyOnce') is not None
    assert bpy.data.collections.get('OnlyOnce.001') is None
    switch = send('switch', 'new_scene', {'use_empty': True})
    wait_depth(1)
    stale = send('queued-old-document', 'create_collection', {'name': 'WrongDocument'})
    wait_depth(2)
    bridge._drain_command_queue()
    assert receive(switch)['ok']
    assert receive(stale)['code'] == 'DOCUMENT_CHANGED'
    assert bpy.data.collections.get('WrongDocument') is None
    bridge.stop_bridge()
    bridge.start_bridge_with_config('127.0.0.1', port, 'test', register_timer=False)
    replay = receive(send('lost-response', 'create_collection', {'name': 'OnlyOnce'}))
    assert replay['ok'], replay
    assert bpy.data.collections.get('OnlyOnce') is None
    diagnostics = receive(send('diagnostics', 'get_diagnostics', {}))['result']
    assert diagnostics['queue_depth'] == 0
    assert diagnostics['running']
finally:
    bridge.stop_bridge()
"""
    )
    result = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "BETTER_BLENDER_STATE_DIR": str(tmp_path / "state")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
