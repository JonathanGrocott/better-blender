"""Better Blender Bridge add-on.

This add-on exposes a local TCP JSON interface that the MCP server can call.
All bpy operations execute on Blender's main thread through a timer-drained queue.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import queue
import shutil
import socketserver
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy

from . import (
    assets,
    checkpoints,
    commands_animation,
    commands_collections,
    commands_nodes,
    commands_objects,
    commands_rendering,
    commands_scene,
    inspection,
)
from .credentials import ensure_token
from .diagnostics import Diagnostics
from .jobs import RenderJobs
from .policy import READ_METHODS, check_path
from .requests import RequestLedger
from .storage import state_directory
from .validation import SCHEMAS, validate_command

bl_info = {
    "name": "Better Blender Bridge",
    "author": "Better Blender Contributors",
    "version": (0, 5, 1),
    "blender": (3, 4, 1),
    "location": "View3D > Sidebar > Better Blender",
    "description": "Local bridge for Better Blender MCP",
    "category": "Development",
}


@dataclass
class BridgeCommand:
    request_id: str
    method: str
    params: dict[str, Any]
    result_queue: queue.Queue[dict[str, Any]]
    deadline: float
    document_id: str = ""
    tracked: bool = False
    state: str = "queued"
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class BridgeRuntime:
    host: str
    port: int
    token: str
    timeout_seconds: float
    read_only: bool = False
    allowed_roots: tuple = ()
    allow_unsafe_code: bool = False
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    scene_pointer: int = 0
    ledger: RequestLedger | None = None
    diagnostics: Diagnostics | None = None
    admission_lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    server: socketserver.ThreadingTCPServer | None = None
    thread: threading.Thread | None = None
    command_queue: queue.Queue[BridgeCommand] | None = None
    render_jobs: RenderJobs = field(default_factory=RenderJobs)


_RUNTIME: BridgeRuntime | None = None
_TIMER_REGISTERED = False
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_CONNECTIONS = 16
MAX_QUEUED_COMMANDS = 128
READ_TIMEOUT = 5.0


class _BridgeTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = False

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[socketserver.BaseRequestHandler],
        runtime: BridgeRuntime,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.runtime = runtime
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)
                request.sendall(
                    b'{"id":"unknown","ok":false,"error":"Bridge busy","code":"BUSY"}\n'
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        self.runtime.diagnostics.connection(1)
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.runtime.diagnostics.connection(-1)
            self.slots.release()


class _BridgeRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.started_at = time.monotonic()
        self.method = "invalid"
        runtime = self.server.runtime  # type: ignore[attr-defined]
        try:
            deadline = time.monotonic() + READ_TIMEOUT
            data = bytearray()
            while b"\n" not in data:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Request read deadline exceeded")
                self.request.settimeout(remaining)
                chunk = self.request.recv(min(65536, MAX_REQUEST_BYTES + 1 - len(data)))
                if not chunk:
                    raise ValueError("Incomplete request")
                data.extend(chunk)
                if len(data) > MAX_REQUEST_BYTES:
                    raise ValueError("Request exceeds 1 MiB limit")
            payload = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request must be an object")
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._write(
                {"id": "unknown", "ok": False, "error": str(exc), "code": "INVALID_REQUEST"}
            )
            return

        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params", {})
        token = payload.get("token")

        if not isinstance(request_id, str) or not isinstance(method, str):
            self._write({"id": "unknown", "ok": False, "error": "Invalid request envelope"})
            return

        if not request_id or len(request_id) > 128 or len(method) > 128:
            self._write({"id": "unknown", "ok": False, "error": "Invalid ID or method length"})
            return
        self.method = method

        if not isinstance(token, str) or not hmac.compare_digest(token, runtime.token):
            self._write({"id": request_id, "ok": False, "error": "Unauthorized"})
            return

        if not isinstance(params, dict):
            self._write({"id": request_id, "ok": False, "error": "params must be an object"})
            return

        if method == "execute_request":
            try:
                validate_command(method, params)
                request_id = params["request_id"]
                payload["expected_document_id"] = params["expected_document_id"]
                method, params = params["method"], params["params"]
                if method == "execute_request" or method in READ_METHODS:
                    raise ValueError("execute_request requires a mutation method")
            except (ValueError, KeyError) as exc:
                self._write({"id": payload["id"], "ok": False, "error": str(exc)})
                return
            # Preserve the transport ID while the journal uses the caller's stable ID.
            self.transport_id = payload["id"]

        if method == "get_diagnostics":
            try:
                validate_command(method, params)
                result = {
                    **runtime.diagnostics.snapshot(),
                    "queue_depth": runtime.command_queue.qsize(),
                    "queue_capacity": MAX_QUEUED_COMMANDS,
                    "running": runtime.running,
                    "session_id": runtime.session_id,
                    "document_id": runtime.document_id,
                    "jobs": runtime.render_jobs.list_jobs(0, 32),
                    "request_journal": runtime.ledger.stats(),
                }
                self._write({"id": request_id, "ok": True, "result": result})
            except ValueError as exc:
                self._write({"id": request_id, "ok": False, "error": str(exc)})
            return

        if method == "get_request_status":
            try:
                validate_command(method, params)
                result = runtime.ledger.status(params["request_id"])
                self._write({"id": request_id, "ok": True, "result": result})
            except ValueError as exc:
                self._write({"id": request_id, "ok": False, "error": str(exc)})
            return

        if method in {"get_job_status", "list_jobs", "get_job_image"}:
            try:
                validate_command(method, params)
                if method == "list_jobs":
                    result = runtime.render_jobs.list_jobs(
                        params.get("offset", 0), params.get("limit", 50)
                    )
                elif method == "get_job_image":
                    if runtime.allowed_roots:
                        job = runtime.render_jobs.status(params["job_id"])
                        for output in (job.get("result") or {}).get("outputs", []):
                            check_path(output, runtime.allowed_roots)
                    result = runtime.render_jobs.image(params["job_id"], params.get("index", 0))
                else:
                    operation = (
                        runtime.render_jobs.status
                        if method == "get_job_status"
                        else runtime.render_jobs.cancel
                    )
                    result = operation(params["job_id"])
                self._write({"id": request_id, "ok": True, "result": result})
            except (ValueError, OSError, sqlite3.Error) as exc:
                self._write({"id": request_id, "ok": False, "error": str(exc)})
            return

        timeout = payload.get("timeout_seconds", runtime.timeout_seconds)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            self._write({"id": request_id, "ok": False, "error": "Invalid timeout_seconds"})
            return
        timeout = min(timeout, runtime.timeout_seconds)
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        command = BridgeCommand(
            request_id=request_id,
            method=method,
            params=params,
            result_queue=result_queue,
            deadline=time.monotonic() + timeout,
            document_id=payload.get("expected_document_id", runtime.document_id),
            tracked=method not in READ_METHODS,
        )

        if runtime.command_queue is None:
            self._write({"id": request_id, "ok": False, "error": "Bridge not initialized"})
            return

        with runtime.admission_lock:
            if not runtime.running:
                self._write(
                    {"id": request_id, "ok": False, "error": "Bridge stopping", "code": "EXPIRED"}
                )
                return
            if command.tracked:
                try:
                    if not runtime.ledger.admit(request_id, method, params):
                        status = runtime.ledger.status(request_id)
                        response = status.get("response") or {
                            "id": request_id,
                            "ok": False,
                            "code": "OUTCOME_UNKNOWN",
                            "error": f"Request is {status['state']}; check get_request_status.",
                        }
                        self._write(response)
                        return
                except (ValueError, OSError, sqlite3.Error) as exc:
                    self._write(
                        {
                            "id": request_id,
                            "ok": False,
                            "error": str(exc),
                            "code": "REQUEST_REJECTED",
                        }
                    )
                    return

            try:
                runtime.command_queue.put_nowait(command)
            except queue.Full:
                if command.tracked:
                    runtime.ledger.update(
                        request_id,
                        "expired",
                        {
                            "id": request_id,
                            "ok": False,
                            "error": "Queue full; no changes made",
                            "code": "BUSY",
                        },
                    )
                self._write(
                    {"id": request_id, "ok": False, "error": "Command queue full", "code": "BUSY"}
                )
                return

        try:
            response = result_queue.get(timeout=max(0, command.deadline - time.monotonic()))
        except queue.Empty:
            # Serialize timeout and execution transitions so an expired queued command
            # can never begin execution after this response is sent.
            with command.lock:
                if command.state == "completed":
                    response = result_queue.get_nowait()
                else:
                    if command.state == "queued":
                        command.state = "expired"
                    running = command.state == "running"
                    response = {
                        "id": request_id,
                        "ok": False,
                        "error": (
                            "Request timed out while executing; outcome unknown. "
                            "The operation may still complete. Do not retry automatically."
                            if running
                            else "Request expired before execution; no changes made."
                        ),
                        "code": "OUTCOME_UNKNOWN" if running else "EXPIRED",
                    }

        self._write(response)

    def _write(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        if hasattr(self, "transport_id"):
            payload["id"] = self.transport_id
        runtime = self.server.runtime
        payload["document_id"] = runtime.document_id
        payload["session_id"] = runtime.session_id
        runtime.diagnostics.record(
            payload.get("id", "unknown"), self.method, payload, time.monotonic() - self.started_at
        )
        try:
            raw = json.dumps(payload, allow_nan=False).encode("utf-8") + b"\n"
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Response exceeds 16 MiB limit")
        except (TypeError, ValueError):
            raw = (
                json.dumps(
                    {
                        "id": payload.get("id", "unknown"),
                        "ok": False,
                        "error": "Response cannot be serialized within limits",
                        "code": "INVALID_RESULT",
                    }
                ).encode()
                + b"\n"
            )
        try:
            self.request.settimeout(5.0)
            self.wfile.write(raw)
            self.wfile.flush()
        except OSError:
            pass  # A disconnected caller must not affect the main-thread queue.


def _to_vector3(raw: Any, field: str) -> tuple[float, float, float]:
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError(f"{field} must be a list of 3 numbers")

    values: list[float] = []
    for value in raw:
        if not isinstance(value, (int, float)):
            raise ValueError(f"{field} must contain only numbers")
        values.append(float(value))

    return (values[0], values[1], values[2])


def _to_quaternion(raw: Any, field: str) -> tuple[float, float, float, float]:
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError(f"{field} must be a list of 4 numbers")

    values: list[float] = []
    for value in raw:
        if not isinstance(value, (int, float)):
            raise ValueError(f"{field} must contain only numbers")
        values.append(float(value))

    return (values[0], values[1], values[2], values[3])


def _normalize_path(raw: Any, *, require_exists: bool) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("filepath must be a non-empty string")

    path = check_path(raw, _RUNTIME.allowed_roots if _RUNTIME else ())
    if require_exists and not path.exists():
        raise ValueError(f"Path does not exist: {path}")

    return str(path)


def _resolve_file_type(filepath: str, file_type: Any) -> str:
    if isinstance(file_type, str) and file_type:
        normalized = file_type.upper()
    else:
        normalized = Path(filepath).suffix.replace(".", "").upper()

    normalized = {"GLB": "GLTF", "USDA": "USD", "USDC": "USD"}.get(normalized, normalized)
    supported = {"OBJ", "FBX", "GLTF", "USD"}
    if normalized not in supported:
        raise ValueError(f"Unsupported file type '{normalized}'. Supported: {sorted(supported)}")

    return normalized


def _serialize_object(obj: bpy.types.Object) -> dict[str, Any]:
    materials: list[str] = []
    if hasattr(obj.data, "materials") and obj.data.materials is not None:
        materials = [mat.name for mat in obj.data.materials if mat is not None]

    return {
        "name": obj.name,
        "type": obj.type,
        "location": [float(v) for v in obj.location],
        "rotation_euler": [float(v) for v in obj.rotation_euler],
        "scale": [float(v) for v in obj.scale],
        "dimensions": [float(v) for v in obj.dimensions],
        "materials": materials,
        **inspection.object_details(obj),
    }


def _require_object(name: Any) -> bpy.types.Object:
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    return obj


def _require_object_mode() -> None:
    if bpy.context.mode != "OBJECT":
        raise ValueError("This operation requires Object Mode. Exit the current mode and retry.")


def _set_active_object(obj: bpy.types.Object) -> None:
    _require_object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _require_collection(name: Any) -> bpy.types.Collection:
    if not isinstance(name, str) or not name:
        raise ValueError("collection name must be a non-empty string")

    collection = bpy.data.collections.get(name)
    if collection is None:
        raise ValueError(f"Collection not found: {name}")
    return collection


def _find_layer_collection(
    layer_collection: bpy.types.LayerCollection,
    target_name: str,
) -> bpy.types.LayerCollection | None:
    if layer_collection.collection.name == target_name:
        return layer_collection

    for child in layer_collection.children:
        found = _find_layer_collection(child, target_name)
        if found is not None:
            return found
    return None


def _require_view_layer(name: str | None) -> bpy.types.ViewLayer:
    scene = bpy.context.scene
    if name is None:
        return bpy.context.view_layer

    view_layer = scene.view_layers.get(name)
    if view_layer is None:
        raise ValueError(f"View layer not found: {name}")
    return view_layer


def _require_modifier(obj: bpy.types.Object, modifier_name: Any) -> bpy.types.Modifier:
    if not isinstance(modifier_name, str) or not modifier_name:
        raise ValueError("modifier_name must be a non-empty string")

    modifier = obj.modifiers.get(modifier_name)
    if modifier is None:
        raise ValueError(f"Modifier not found: {modifier_name}")
    return modifier


def _ensure_geometry_nodes_group(modifier: bpy.types.Modifier) -> bpy.types.NodeTree:
    node_group = modifier.node_group
    created = node_group is None
    if node_group is None:
        node_group = bpy.data.node_groups.new(name=f"{modifier.name}Tree", type="GeometryNodeTree")
        modifier.node_group = node_group

    nodes = node_group.nodes
    links = node_group.links

    group_input = nodes.get("Group Input")
    if group_input is None:
        group_input = nodes.new("NodeGroupInput")

    group_output = nodes.get("Group Output")
    if group_output is None:
        group_output = nodes.new("NodeGroupOutput")

    if hasattr(node_group, "interface") and not node_group.interface.items_tree:
        node_group.interface.new_socket(
            name="Geometry",
            in_out="INPUT",
            socket_type="NodeSocketGeometry",
        )
        node_group.interface.new_socket(
            name="Geometry",
            in_out="OUTPUT",
            socket_type="NodeSocketGeometry",
        )
    elif not hasattr(node_group, "interface"):
        if not node_group.inputs:
            node_group.inputs.new("NodeSocketGeometry", "Geometry")
        if not node_group.outputs:
            node_group.outputs.new("NodeSocketGeometry", "Geometry")

    if (
        created
        and "Geometry" in group_input.outputs
        and "Geometry" in group_output.inputs
        and not any(
            link.from_socket == group_input.outputs["Geometry"]
            and link.to_socket == group_output.inputs["Geometry"]
            for link in links
        )
    ):
        links.new(group_input.outputs["Geometry"], group_output.inputs["Geometry"])

    return node_group


def _require_node_tree(scene: bpy.types.Scene) -> bpy.types.NodeTree:
    tree = getattr(scene, "node_tree", None)
    if tree is not None:
        return tree

    group_tree = getattr(scene, "compositing_node_group", None)
    if group_tree is not None:
        return group_tree

    raise ValueError("Compositor nodes are disabled. Call enable_compositor first.")


def _get_or_create_compositor_tree(scene: bpy.types.Scene) -> bpy.types.NodeTree:
    tree = getattr(scene, "node_tree", None)
    if tree is not None:
        return tree

    group_tree = getattr(scene, "compositing_node_group", None)
    if group_tree is not None:
        return group_tree

    created = bpy.data.node_groups.new(name=f"{scene.name}_Compositor", type="CompositorNodeTree")
    if hasattr(scene, "compositing_node_group"):
        scene.compositing_node_group = created
    return created


def _iter_action_fcurves(action: bpy.types.Action) -> list[bpy.types.FCurve]:
    if hasattr(action, "fcurves"):
        return list(action.fcurves)

    fcurves: list[bpy.types.FCurve] = []
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbags"):
                    for channelbag in strip.channelbags:
                        if hasattr(channelbag, "fcurves"):
                            fcurves.extend(channelbag.fcurves)
    return fcurves


def _require_action(name: Any) -> bpy.types.Action:
    if not isinstance(name, str) or not name:
        raise ValueError("action name must be a non-empty string")

    action = bpy.data.actions.get(name)
    if action is None:
        raise ValueError(f"Action not found: {name}")
    return action


def _require_nla_track(obj: bpy.types.Object, track_name: Any) -> bpy.types.NlaTrack:
    if obj.animation_data is None:
        raise ValueError(f"Object {obj.name} has no animation data")

    if not isinstance(track_name, str) or not track_name:
        raise ValueError("track_name must be a non-empty string")

    track = obj.animation_data.nla_tracks.get(track_name)
    if track is None:
        raise ValueError(f"NLA track not found: {track_name}")
    return track


def _require_nla_strip(track: bpy.types.NlaTrack, strip_name: Any) -> bpy.types.NlaStrip:
    if not isinstance(strip_name, str) or not strip_name:
        raise ValueError("strip_name must be a non-empty string")

    strip = track.strips.get(strip_name)
    if strip is None:
        raise ValueError(f"NLA strip not found: {strip_name}")
    return strip


def _serialize_nla_strip(strip: bpy.types.NlaStrip) -> dict[str, Any]:
    action_name = strip.action.name if strip.action is not None else None
    return {
        "name": strip.name,
        "action": action_name,
        "frame_start": float(strip.frame_start),
        "frame_end": float(strip.frame_end),
        "action_frame_start": float(strip.action_frame_start),
        "action_frame_end": float(strip.action_frame_end),
        "scale": float(strip.scale),
        "repeat": float(strip.repeat),
        "mute": bool(strip.mute),
    }


def _resolve_geometry_input_identifier(
    node_group: bpy.types.NodeTree,
    input_name_or_identifier: Any,
) -> tuple[str, str]:
    if not isinstance(input_name_or_identifier, str) or not input_name_or_identifier:
        raise ValueError("input_name_or_identifier must be a non-empty string")

    if hasattr(node_group, "interface"):
        items = [item for item in node_group.interface.items_tree if item.item_type == "SOCKET"]
        for item in items:
            if item.in_out != "INPUT":
                continue
            if getattr(item, "identifier", "") == input_name_or_identifier:
                return item.identifier, item.name

        for item in items:
            if item.in_out != "INPUT":
                continue
            if item.name == input_name_or_identifier:
                return item.identifier, item.name
    else:
        for socket in node_group.inputs:
            identifier = socket.identifier if hasattr(socket, "identifier") else socket.name
            if identifier == input_name_or_identifier:
                return identifier, socket.name
        for socket in node_group.inputs:
            if socket.name == input_name_or_identifier:
                identifier = socket.identifier if hasattr(socket, "identifier") else socket.name
                return identifier, socket.name

    raise ValueError(f"Geometry input not found: {input_name_or_identifier}")


def _ensure_subject_object(
    object_name: str,
    primitive: str = "CUBE",
    size: float = 2.0,
) -> bpy.types.Object:
    obj = bpy.data.objects.get(object_name)
    if obj is not None:
        return obj

    primitive = primitive.upper()
    if primitive == "CUBE":
        bpy.ops.mesh.primitive_cube_add(size=size, location=(0.0, 0.0, size / 2))
    elif primitive == "UV_SPHERE":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=size / 2, location=(0.0, 0.0, size / 2))
    elif primitive == "CYLINDER":
        bpy.ops.mesh.primitive_cylinder_add(
            radius=size / 2,
            depth=size,
            location=(0.0, 0.0, size / 2),
        )
    else:
        raise ValueError(f"Unsupported primitive for workflow: {primitive}")

    created = bpy.context.active_object
    if created is None:
        raise RuntimeError("Failed to create subject object")
    created.name = object_name
    return created


def _create_or_update_light(
    name: str,
    light_type: str,
    energy: float,
    location: tuple[float, float, float],
) -> bpy.types.Object:
    light_object = bpy.data.objects.get(name)
    if light_object is not None and light_object.type == "LIGHT":
        light_object.location = location
        if hasattr(light_object.data, "energy"):
            light_object.data.energy = energy
        return light_object

    light_data = bpy.data.lights.new(name=f"{name}Data", type=light_type)
    light_data.energy = energy
    light_object = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(light_object)
    light_object.location = location
    return light_object


def _find_view3d_context() -> (
    tuple[
        bpy.types.Window,
        bpy.types.Area,
        bpy.types.Region,
        bpy.types.SpaceView3D,
        bpy.types.RegionView3D,
    ]
    | None
):
    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue

        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            if not area.spaces:
                continue

            space = area.spaces.active
            if not isinstance(space, bpy.types.SpaceView3D):
                continue

            region = next((reg for reg in area.regions if reg.type == "WINDOW"), None)
            if region is None:
                continue

            region_3d = space.region_3d
            if region_3d is None:
                continue

            return window, area, region, space, region_3d
    return None


def _capture_viewport(params: dict[str, Any]) -> dict[str, Any]:
    filepath = _normalize_path(params.get("filepath"), require_exists=False)
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    context = _find_view3d_context()
    fallback_to_render = bool(params.get("fallback_to_render", True))

    if bpy.app.background:
        context = None

    if context is None:
        if not fallback_to_render:
            raise ValueError("No VIEW_3D viewport context available (likely headless mode)")

        render_params: dict[str, Any] = {"filepath": filepath}
        for key in ("engine", "resolution_x", "resolution_y", "samples"):
            if key in params:
                render_params[key] = params[key]
        result = _dispatch_command("render_still", render_params)
        result["capture_mode"] = "render_fallback_no_viewport"
        result["viewport_available"] = False
        result["captured"] = True
        return result

    window, area, region, _, _ = context

    view_params: dict[str, Any] = {}
    for key in (
        "view",
        "location",
        "rotation_quaternion",
        "distance",
        "lens",
        "shading_type",
    ):
        if key in params:
            view_params[key] = params[key]
    if view_params:
        _dispatch_command("set_viewport_view", view_params)

    scene = bpy.context.scene
    old_filepath = scene.render.filepath
    old_res_x = scene.render.resolution_x
    old_res_y = scene.render.resolution_y
    try:
        scene.render.filepath = filepath
        if isinstance(params.get("resolution_x"), int) and params.get("resolution_x") > 0:
            scene.render.resolution_x = int(params.get("resolution_x"))
        if isinstance(params.get("resolution_y"), int) and params.get("resolution_y") > 0:
            scene.render.resolution_y = int(params.get("resolution_y"))

        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.render.opengl(write_still=True, view_context=True)
    finally:
        scene.render.filepath = old_filepath
        scene.render.resolution_x = old_res_x
        scene.render.resolution_y = old_res_y

    return {
        "captured": True,
        "filepath": filepath,
        "capture_mode": "viewport_opengl",
        "viewport_available": True,
    }


def _require_material(name: str) -> bpy.types.Material:
    material = bpy.data.materials.get(name)
    if material is None:
        raise ValueError(f"Material not found: {name}")
    return material


def _preflight(method: str, params: dict[str, Any]) -> None:
    validate_command(method, params)
    # Resolve references before any data-blocks or properties are changed.
    for key in ("target_name", "parent_name", "view_layer_name", "material_name", "action_name"):
        value = params.get(key)
        if value is None:
            continue
        resolver = {
            "target_name": _require_object,
            "parent_name": _require_collection,
            "view_layer_name": _require_view_layer,
            "material_name": _require_material,
            "action_name": _require_action,
        }[key]
        resolver(value)
    if params.get("object_name") is not None and method not in {
        "workflow_setup_studio",
        "workflow_turntable_render",
    }:
        _require_object(params["object_name"])
    if "frame_start" in params or "frame_end" in params:
        start = params.get("frame_start", bpy.context.scene.frame_start)
        end = params.get("frame_end", bpy.context.scene.frame_end)
        if start > end:
            raise ValueError("frame_start must not exceed frame_end")
    if method in {"workflow_setup_studio", "workflow_turntable_render"}:
        _require_object_mode()
    if "engine" in params:
        # Engine enum items are dynamic and can be empty through RNA introspection.
        render = bpy.context.scene.render
        previous = render.engine
        try:
            render.engine = params["engine"]
        finally:
            render.engine = previous


def _dispatch_command(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if _RUNTIME is not None:
        if _RUNTIME.read_only and method not in READ_METHODS:
            raise ValueError("Bridge is in read-only mode")
        if method == "execute_code" and _RUNTIME.allowed_roots:
            raise ValueError("Unsafe code is disabled when path restrictions are configured")

    checkpoint_operations = {
        "delete_checkpoint": lambda: checkpoints.delete(params["checkpoint_id"]),
        "get_checkpoint_usage": checkpoints.usage,
        "configure_checkpoint_retention": lambda: checkpoints.configure(
            params["max_count"], params["max_bytes"]
        ),
        "check_assets": lambda: checkpoints.check_assets(params.get("checkpoint_id")),
    }
    if method in checkpoint_operations:
        validate_command(method, params)
        return checkpoint_operations[method]()
    if method == "cancel_job":
        validate_command(method, params)
        return _RUNTIME.render_jobs.cancel(params["job_id"])
    if method == "get_document_context":
        validate_command(method, params)
        return {
            "document_id": _RUNTIME.document_id,
            "session_id": _RUNTIME.session_id,
            "filepath": bpy.data.filepath,
            "scene": bpy.context.scene.name,
        }

    if method in {
        "create_checkpoint",
        "list_checkpoints",
        "restore_checkpoint",
        "run_with_checkpoint",
    }:
        validate_command(method, params)
        if method == "create_checkpoint":
            return checkpoints.create(params.get("label", "Checkpoint"))
        if method == "list_checkpoints":
            return checkpoints.list_checkpoints(params.get("offset", 0), params.get("limit", 50))
        if method == "restore_checkpoint":
            return checkpoints.restore(
                params["checkpoint_id"],
                params.get("backup_current", True),
                params.get("allow_missing_assets", False),
            )
        _preflight(params["method"], params["params"])
        saved = checkpoints.create(params.get("label", "Before destructive operation"))
        try:
            result = _dispatch_command(params["method"], params["params"])
        except Exception as exc:
            raise RuntimeError(f"{exc}. Recovery checkpoint: {saved['checkpoint_id']}") from exc
        return {"result": result, "recovery_checkpoint": saved}
    if method == "start_render_job":
        validate_command(method, params)
        render_method = params["method"]
        render_params = params["params"]
        _preflight(render_method, render_params)
        assets.require_available()
        for key in ("filepath", "output_path"):
            if render_params.get(key):
                _normalize_path(render_params[key], require_exists=False)
        if _RUNTIME is None:
            raise ValueError("Bridge runtime unavailable")
        directory = _RUNTIME.render_jobs.create_workspace()
        try:
            snapshot = directory / "scene.blend"
            # Capture dependencies with absolute paths without changing the user's file.
            bpy.data.libraries.write(str(snapshot), {bpy.context.scene}, path_remap="ABSOLUTE")
            return _RUNTIME.render_jobs.submit(
                bpy.app.binary_path,
                snapshot,
                {
                    "method": render_method,
                    "params": render_params,
                    "scene_name": bpy.context.scene.name,
                },
                directory,
            )
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
    if method in {"render_still", "render_animation", "workflow_turntable_render"}:
        assets.require_available()
    _preflight(method, params)
    for domain in (
        commands_scene,
        commands_objects,
        commands_animation,
        commands_nodes,
        commands_rendering,
        commands_collections,
    ):
        if method in domain.METHODS:
            return domain.dispatch(method, params, sys.modules[__name__])
    if method == "health":
        return {
            "bridge_running": True,
            "protocol_version": 1,
            "capabilities": {
                "render_jobs": True,
                "render_supervision": True,
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
            "bridge_version": ".".join(str(v) for v in bl_info["version"]),
            "blender_version": bpy.app.version_string,
            "file_path": bpy.data.filepath,
            "timestamp": time.time(),
            "supported_methods": _supported_methods(),
        }

    if method == "execute_code":
        allow_unsafe_code = _RUNTIME.allow_unsafe_code if _RUNTIME is not None else False
        if not allow_unsafe_code:
            raise ValueError("Unsafe code execution is disabled in add-on preferences")

        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")

        local_vars: dict[str, Any] = {}
        exec(code, {"bpy": bpy}, local_vars)
        result = local_vars.get("result")

        try:
            json.dumps(result)
            serialized_result: Any = result
        except TypeError:
            serialized_result = repr(result)

        return {"result": serialized_result}

    raise ValueError(f"Unsupported method: {method}")


def _supported_methods() -> list[str]:
    return sorted(SCHEMAS)


@bpy.app.handlers.persistent
def _document_loaded(_unused):
    if _RUNTIME is not None:
        _RUNTIME.document_id = str(uuid.uuid4())
        _RUNTIME.scene_pointer = bpy.context.scene.as_pointer()


def _sync_document(runtime):
    pointer = bpy.context.scene.as_pointer()
    if runtime.scene_pointer != pointer:
        runtime.document_id = str(uuid.uuid4())
        runtime.scene_pointer = pointer


def _finish_command(runtime, command, response, state="completed"):
    try:
        json.dumps(response, allow_nan=False)
    except (ValueError, TypeError):
        response = {
            "id": command.request_id,
            "ok": False,
            "error": "Result cannot be serialized",
            "code": "INVALID_RESULT",
        }
    if command.tracked:
        try:
            runtime.ledger.update(command.request_id, state, response)
        except (OSError, sqlite3.Error):
            response = {
                "id": command.request_id,
                "ok": False,
                "code": "JOURNAL_ERROR",
                "error": "Cannot persist outcome; inspect the document before a new request.",
            }
    command.state = state
    if command.result_queue.empty():
        command.result_queue.put_nowait(response)


def _drain_command_queue() -> float | None:
    global _TIMER_REGISTERED
    runtime = _RUNTIME
    if runtime is None or not runtime.running or runtime.command_queue is None:
        _TIMER_REGISTERED = False
        return None
    _sync_document(runtime)
    for _ in range(25):
        try:
            command = runtime.command_queue.get_nowait()
        except queue.Empty:
            break
        with command.lock:
            if command.state == "expired" or time.monotonic() >= command.deadline:
                _finish_command(
                    runtime,
                    command,
                    {
                        "id": command.request_id,
                        "ok": False,
                        "error": "Request expired before execution; no changes made.",
                        "code": "EXPIRED",
                    },
                    "expired",
                )
                continue
            _sync_document(runtime)
            if command.tracked and command.document_id != runtime.document_id:
                _finish_command(
                    runtime,
                    command,
                    {
                        "id": command.request_id,
                        "ok": False,
                        "code": "DOCUMENT_CHANGED",
                        "error": "Document or scene changed; inspect it before a new edit.",
                    },
                )
                continue
            if command.tracked:
                try:
                    runtime.ledger.update(command.request_id, "running")
                except (OSError, sqlite3.Error):
                    _finish_command(
                        runtime,
                        command,
                        {
                            "id": command.request_id,
                            "ok": False,
                            "code": "JOURNAL_ERROR",
                            "error": "Journal unavailable; operation was not started.",
                        },
                        "expired",
                    )
                    continue
            command.state = "running"
        started = time.monotonic()
        try:
            result = _dispatch_command(command.method, command.params)
            response = {"id": command.request_id, "ok": True, "result": result}
        except Exception as exc:
            response = {"id": command.request_id, "ok": False, "error": str(exc)}
        runtime.diagnostics.record(
            command.request_id, command.method, response, time.monotonic() - started, "execution"
        )
        _sync_document(runtime)
        with command.lock:
            _finish_command(runtime, command, response)
    return 0.05


def _register_timer_if_needed() -> None:
    global _TIMER_REGISTERED

    if _TIMER_REGISTERED:
        return

    bpy.app.timers.register(_drain_command_queue, persistent=True)
    _TIMER_REGISTERED = True


def _get_addon_prefs(context: bpy.types.Context | None = None) -> BetterBlenderPreferences:
    ctx = context or bpy.context
    addon = ctx.preferences.addons.get(__name__)
    if addon is None:
        raise RuntimeError("Add-on preferences not available")

    prefs = addon.preferences
    if not isinstance(prefs, BetterBlenderPreferences):
        raise RuntimeError("Unexpected add-on preferences type")

    return prefs


def start_bridge(context: bpy.types.Context | None = None) -> None:
    prefs = _get_addon_prefs(context)
    start_bridge_with_config(
        host=prefs.host,
        port=prefs.port,
        token=prefs.token if prefs.token and prefs.token != "change-me" else ensure_token(),
        read_only=prefs.read_only,
        allowed_roots=(prefs.allowed_directory,) if prefs.allowed_directory else (),
        allow_remote=prefs.allow_remote,
        render_timeout_seconds=prefs.render_timeout_seconds,
        timeout_seconds=prefs.timeout_seconds,
        allow_unsafe_code=prefs.allow_unsafe_code,
        register_timer=True,
    )


def start_bridge_with_config(
    host: str,
    port: int,
    token: str,
    timeout_seconds: float = 30.0,
    allow_unsafe_code: bool = False,
    register_timer: bool = True,
    read_only: bool = False,
    allowed_roots: tuple = (),
    allow_remote: bool = False,
    render_timeout_seconds: float = 3600.0,
) -> None:
    global _RUNTIME

    if _RUNTIME is not None and _RUNTIME.running:
        return

    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if not loopback and not allow_remote:
        raise ValueError("Nonlocal binding requires explicit allow_remote opt-in")
    if not token or token == "change-me":
        token = ensure_token()
    if not loopback and len(token) < 32:
        raise ValueError("Nonlocal binding requires a token of at least 32 characters")
    runtime = BridgeRuntime(
        read_only=read_only,
        allowed_roots=tuple(Path(root).expanduser().resolve() for root in allowed_roots),
        host=host,
        port=port,
        token=token,
        timeout_seconds=timeout_seconds,
        allow_unsafe_code=allow_unsafe_code,
        running=True,
        command_queue=queue.Queue(maxsize=MAX_QUEUED_COMMANDS),
    )

    try:
        server = _BridgeTCPServer((runtime.host, runtime.port), _BridgeRequestHandler, runtime)
        runtime.server = server
        namespace = hashlib.sha256(f"{host}:{server.server_address[1]}".encode()).hexdigest()[:16]
        runtime.render_jobs = RenderJobs(
            state_directory() / "jobs" / namespace, timeout_seconds=render_timeout_seconds
        )
        runtime.ledger = RequestLedger(state_directory() / "requests" / (namespace + ".sqlite3"))
        runtime.scene_pointer = bpy.context.scene.as_pointer()
        runtime.diagnostics = Diagnostics(state_directory() / "logs" / (namespace + ".jsonl"))
        thread = threading.Thread(
            target=server.serve_forever, name="better-blender-bridge", daemon=True
        )
        runtime.thread = thread
        _RUNTIME = runtime
        if _document_loaded not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(_document_loaded)
        if register_timer:
            _register_timer_if_needed()
        thread.start()
    except Exception:
        _dispose_runtime(runtime)
        raise


def _dispose_runtime(runtime):
    """Release every acquired resource, including partially initialized runtimes."""
    global _RUNTIME, _TIMER_REGISTERED
    errors = []

    def attempt(operation):
        try:
            operation()
        except Exception as exc:
            errors.append(exc)

    if bpy.app.timers.is_registered(_drain_command_queue):
        attempt(lambda: bpy.app.timers.unregister(_drain_command_queue))
    _TIMER_REGISTERED = False
    with runtime.admission_lock:
        runtime.running = False
    if _document_loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_document_loaded)
    while runtime.command_queue is not None:
        try:
            command = runtime.command_queue.get_nowait()
        except queue.Empty:
            break
        with command.lock:
            _finish_command(
                runtime,
                command,
                {
                    "id": command.request_id,
                    "ok": False,
                    "error": "Bridge stopped before execution",
                    "code": "EXPIRED",
                },
                "expired",
            )
    attempt(runtime.render_jobs.shutdown)
    if runtime.server is not None:
        # shutdown() waits forever if serve_forever never started.
        if runtime.thread is not None and runtime.thread.is_alive():
            attempt(runtime.server.shutdown)
        # Non-daemon request threads finish before their shared DB/log handles close.
        attempt(runtime.server.server_close)
    if runtime.thread is not None and runtime.thread.is_alive():
        attempt(runtime.thread.join)
    if runtime.ledger is not None:
        attempt(runtime.ledger.close)
    if runtime.diagnostics is not None:
        attempt(runtime.diagnostics.close)
    if _RUNTIME is runtime:
        _RUNTIME = None
    return errors


def stop_bridge() -> None:
    if _RUNTIME is None:
        return
    errors = _dispose_runtime(_RUNTIME)
    if errors:
        raise RuntimeError("Bridge cleanup encountered errors: " + "; ".join(map(str, errors)))


class BetterBlenderPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    host: bpy.props.StringProperty(name="Host", default="127.0.0.1")
    port: bpy.props.IntProperty(name="Port", default=8765, min=1024, max=65535)
    token: bpy.props.StringProperty(name="Token override", default="", subtype="PASSWORD")
    read_only: bpy.props.BoolProperty(name="Read-only mode", default=False)
    allowed_directory: bpy.props.StringProperty(
        name="Allowed tool directory", default="", subtype="DIR_PATH"
    )
    allow_remote: bpy.props.BoolProperty(name="Allow nonlocal binding", default=False)
    timeout_seconds: bpy.props.FloatProperty(
        name="Request Timeout", default=30.0, min=1.0, max=300.0
    )
    render_timeout_seconds: bpy.props.FloatProperty(
        name="Render Runtime Limit",
        description="Maximum seconds per render job",
        default=3600.0,
        min=1.0,
        max=604800.0,
    )
    allow_unsafe_code: bpy.props.BoolProperty(
        name="Allow Unsafe Code Execution",
        description="Allow execute_code bridge method",
        default=False,
    )

    def draw(self, context: bpy.types.Context) -> None:
        del context
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.prop(self, "token")
        layout.prop(self, "timeout_seconds")
        layout.prop(self, "render_timeout_seconds")
        layout.prop(self, "allow_unsafe_code")
        layout.prop(self, "read_only")
        layout.prop(self, "allowed_directory")
        layout.prop(self, "allow_remote")


class BbOtStartBridge(bpy.types.Operator):
    bl_idname = "better_blender.start_bridge"
    bl_label = "Start Bridge"
    bl_description = "Start the Better Blender local bridge"

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            start_bridge(context)
        except Exception as exc:  # pylint: disable=broad-except
            self.report({"ERROR"}, f"Failed to start bridge: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Better Blender bridge started")
        return {"FINISHED"}


class BbOtStopBridge(bpy.types.Operator):
    bl_idname = "better_blender.stop_bridge"
    bl_label = "Stop Bridge"
    bl_description = "Stop the Better Blender local bridge"

    def execute(self, context: bpy.types.Context) -> set[str]:
        del context
        stop_bridge()
        self.report({"INFO"}, "Better Blender bridge stopped")
        return {"FINISHED"}


class BbPtBridgePanel(bpy.types.Panel):
    bl_label = "Better Blender"
    bl_idname = "BB_PT_bridge_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Better Blender"

    def draw(self, context: bpy.types.Context) -> None:
        del context
        layout = self.layout
        row = layout.row(align=True)
        row.operator(BbOtStartBridge.bl_idname, icon="PLAY")
        row.operator(BbOtStopBridge.bl_idname, icon="PAUSE")

        if _RUNTIME is None or not _RUNTIME.running:
            layout.label(text="Status: stopped", icon="ERROR")
        else:
            status = f"Status: running on {_RUNTIME.host}:{_RUNTIME.port}"
            layout.label(text=status, icon="CHECKMARK")


_CLASSES = [
    BetterBlenderPreferences,
    BbOtStartBridge,
    BbOtStopBridge,
    BbPtBridgePanel,
]


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    stop_bridge()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
