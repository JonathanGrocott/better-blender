"""Better Blender Bridge add-on.

This add-on exposes a local TCP JSON interface that the MCP server can call.
All bpy operations execute on Blender's main thread through a timer-drained queue.
"""

from __future__ import annotations

import json
import math
import queue
import socketserver
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy
from mathutils import Quaternion, Vector

bl_info = {
    "name": "Better Blender Bridge",
    "author": "Better Blender Contributors",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
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


@dataclass
class BridgeRuntime:
    host: str
    port: int
    token: str
    timeout_seconds: float
    allow_unsafe_code: bool = False
    running: bool = False
    server: socketserver.ThreadingTCPServer | None = None
    thread: threading.Thread | None = None
    command_queue: queue.Queue[BridgeCommand] | None = None


_RUNTIME: BridgeRuntime | None = None
_TIMER_REGISTERED = False


class _BridgeTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[socketserver.BaseRequestHandler],
        runtime: BridgeRuntime,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.runtime = runtime


class _BridgeRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        runtime = self.server.runtime  # type: ignore[attr-defined]
        line = self.rfile.readline()
        if not line:
            return

        try:
            payload = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            self._write({"id": "unknown", "ok": False, "error": "Invalid JSON"})
            return

        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params", {})
        token = payload.get("token")

        if not isinstance(request_id, str) or not isinstance(method, str):
            self._write({"id": "unknown", "ok": False, "error": "Invalid request envelope"})
            return

        if token != runtime.token:
            self._write({"id": request_id, "ok": False, "error": "Unauthorized"})
            return

        if not isinstance(params, dict):
            self._write({"id": request_id, "ok": False, "error": "params must be an object"})
            return

        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        command = BridgeCommand(
            request_id=request_id,
            method=method,
            params=params,
            result_queue=result_queue,
        )

        if runtime.command_queue is None:
            self._write({"id": request_id, "ok": False, "error": "Bridge not initialized"})
            return

        runtime.command_queue.put(command)

        try:
            response = result_queue.get(timeout=runtime.timeout_seconds)
        except queue.Empty:
            self._write({"id": request_id, "ok": False, "error": "Request timed out"})
            return

        self._write(response)

    def _write(self, payload: dict[str, Any]) -> None:
        self.wfile.write(json.dumps(payload).encode("utf-8") + b"\n")
        self.wfile.flush()


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

    path = Path(raw).expanduser().resolve()
    if require_exists and not path.exists():
        raise ValueError(f"Path does not exist: {path}")

    return str(path)


def _resolve_file_type(filepath: str, file_type: Any) -> str:
    if isinstance(file_type, str) and file_type:
        normalized = file_type.upper()
    else:
        normalized = Path(filepath).suffix.replace(".", "").upper()

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
    }


def _require_object(name: Any) -> bpy.types.Object:
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    return obj


def _set_active_object(obj: bpy.types.Object) -> None:
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
        "Geometry" in group_input.outputs
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


def _dispatch_command(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "health":
        return {
            "bridge_running": True,
            "blender_version": bpy.app.version_string,
            "file_path": bpy.data.filepath,
            "timestamp": time.time(),
            "supported_methods": _supported_methods(),
        }

    if method == "new_scene":
        use_empty = bool(params.get("use_empty", True))
        bpy.ops.wm.read_homefile(use_empty=use_empty)
        return _dispatch_command("get_scene_info", {})

    if method == "open_blend":
        filepath = _normalize_path(params.get("filepath"), require_exists=True)
        bpy.ops.wm.open_mainfile(filepath=filepath)
        return _dispatch_command("get_scene_info", {})

    if method == "save_blend":
        filepath = params.get("filepath")
        if filepath is None:
            if not bpy.data.filepath:
                raise ValueError("Current blend file has no path. Provide filepath.")
            bpy.ops.wm.save_mainfile()
        else:
            normalized = _normalize_path(filepath, require_exists=False)
            Path(normalized).parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=normalized)

        return {"file_path": bpy.data.filepath}

    if method == "get_scene_info":
        scene = bpy.context.scene
        return {
            "scene_name": scene.name,
            "frame_current": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "objects_total": len(scene.objects),
            "collections_total": len(bpy.data.collections),
            "file_path": bpy.data.filepath,
        }

    if method == "set_timeline":
        scene = bpy.context.scene

        frame_start = params.get("frame_start")
        frame_end = params.get("frame_end")
        frame_current = params.get("frame_current")
        fps = params.get("fps")

        if isinstance(frame_start, int):
            scene.frame_start = frame_start
        if isinstance(frame_end, int):
            scene.frame_end = frame_end
        if isinstance(frame_current, int):
            scene.frame_set(frame_current)
        if isinstance(fps, int) and fps > 0:
            scene.render.fps = fps

        return {
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "frame_current": scene.frame_current,
            "fps": scene.render.fps,
        }

    if method == "list_objects":
        scene = bpy.context.scene
        objects = [_serialize_object(obj) for obj in scene.objects]
        return {"objects": objects, "count": len(objects)}

    if method == "get_object_info":
        obj = _require_object(params.get("name"))
        return {"object": _serialize_object(obj)}

    if method == "create_primitive":
        primitive = params.get("primitive", "CUBE")
        if not isinstance(primitive, str):
            raise ValueError("primitive must be a string")

        primitive = primitive.upper()
        name = params.get("name")
        location = _to_vector3(params.get("location", [0.0, 0.0, 0.0]), "location")
        rotation = _to_vector3(params.get("rotation", [0.0, 0.0, 0.0]), "rotation")
        scale = _to_vector3(params.get("scale", [1.0, 1.0, 1.0]), "scale")
        size = float(params.get("size", 2.0))

        if primitive == "CUBE":
            bpy.ops.mesh.primitive_cube_add(
                size=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "UV_SPHERE":
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=size / 2,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "ICO_SPHERE":
            bpy.ops.mesh.primitive_ico_sphere_add(
                radius=size / 2,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "CYLINDER":
            bpy.ops.mesh.primitive_cylinder_add(
                radius=size / 2,
                depth=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "CONE":
            bpy.ops.mesh.primitive_cone_add(
                radius1=size / 2,
                depth=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "PLANE":
            bpy.ops.mesh.primitive_plane_add(
                size=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "TORUS":
            bpy.ops.mesh.primitive_torus_add(
                major_radius=size / 2,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "MONKEY":
            bpy.ops.mesh.primitive_monkey_add(
                size=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        else:
            raise ValueError(f"Unsupported primitive: {primitive}")

        obj = bpy.context.active_object
        if obj is None:
            raise RuntimeError("Primitive creation did not produce an active object")

        if isinstance(name, str) and name:
            obj.name = name

        return {"object": _serialize_object(obj)}

    if method == "delete_object":
        obj = _require_object(params.get("name"))
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"deleted": obj.name}

    if method == "set_object_transform":
        obj = _require_object(params.get("name"))

        if "location" in params:
            obj.location = _to_vector3(params["location"], "location")
        if "rotation" in params:
            obj.rotation_euler = _to_vector3(params["rotation"], "rotation")
        if "scale" in params:
            obj.scale = _to_vector3(params["scale"], "scale")

        return {"object": _serialize_object(obj)}

    if method == "duplicate_object":
        obj = _require_object(params.get("name"))
        new_name = params.get("new_name")
        linked = bool(params.get("linked", False))

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.duplicate(linked=linked)

        duplicated = bpy.context.active_object
        if duplicated is None:
            raise RuntimeError("Duplicate operation did not return an active object")

        if isinstance(new_name, str) and new_name:
            duplicated.name = new_name

        return {"object": _serialize_object(duplicated)}

    if method == "keyframe_transform":
        obj = _require_object(params.get("name"))
        frame = params.get("frame")
        if not isinstance(frame, int):
            raise ValueError("frame must be an integer")

        location_set = "location" in params
        rotation_set = "rotation" in params
        scale_set = "scale" in params
        if not location_set and not rotation_set and not scale_set:
            raise ValueError("At least one of location, rotation, or scale must be provided")

        if location_set:
            obj.location = _to_vector3(params["location"], "location")
            obj.keyframe_insert(data_path="location", frame=frame)
        if rotation_set:
            obj.rotation_euler = _to_vector3(params["rotation"], "rotation")
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)
        if scale_set:
            obj.scale = _to_vector3(params["scale"], "scale")
            obj.keyframe_insert(data_path="scale", frame=frame)

        return {"object": _serialize_object(obj), "frame": frame}

    if method == "insert_keyframe":
        obj = _require_object(params.get("name"))
        data_path = params.get("data_path")
        frame = params.get("frame")
        index = params.get("index", -1)

        if not isinstance(data_path, str) or not data_path:
            raise ValueError("data_path must be a non-empty string")
        if not isinstance(frame, int):
            raise ValueError("frame must be an integer")
        if not isinstance(index, int):
            raise ValueError("index must be an integer")

        inserted = obj.keyframe_insert(data_path=data_path, frame=frame, index=index)
        return {
            "inserted": bool(inserted),
            "name": obj.name,
            "data_path": data_path,
            "frame": frame,
            "index": index,
        }

    if method == "list_animation_data":
        obj = _require_object(params.get("name"))
        animation_data = obj.animation_data
        if animation_data is None or animation_data.action is None:
            return {"name": obj.name, "has_animation": False, "action": None, "fcurves": []}

        action = animation_data.action
        curves = _iter_action_fcurves(action)
        fcurves = []
        for fcurve in curves:
            fcurves.append(
                {
                    "data_path": fcurve.data_path,
                    "array_index": fcurve.array_index,
                    "keyframes": len(fcurve.keyframe_points),
                }
            )

        return {
            "name": obj.name,
            "has_animation": True,
            "action": action.name,
            "fcurves": fcurves,
        }

    if method == "list_actions":
        actions = [{"name": action.name, "users": action.users} for action in bpy.data.actions]
        return {"actions": actions, "count": len(actions)}

    if method == "create_action":
        action_name = params.get("name")
        object_name = params.get("object_name")
        set_active = bool(params.get("set_active", True))

        if not isinstance(action_name, str) or not action_name:
            raise ValueError("name must be a non-empty string")

        action = bpy.data.actions.get(action_name)
        if action is None:
            action = bpy.data.actions.new(name=action_name)

        if isinstance(object_name, str) and object_name:
            obj = _require_object(object_name)
            if obj.animation_data is None:
                obj.animation_data_create()
            if set_active:
                obj.animation_data.action = action

        return {"action": {"name": action.name, "users": action.users}}

    if method == "set_active_action":
        object_name = params.get("object_name")
        action_name = params.get("action_name")

        obj = _require_object(object_name)
        if not isinstance(action_name, str) or not action_name:
            raise ValueError("action_name must be a non-empty string")

        action = bpy.data.actions.get(action_name)
        if action is None:
            raise ValueError(f"Action not found: {action_name}")

        if obj.animation_data is None:
            obj.animation_data_create()
        obj.animation_data.action = action
        return {"object_name": obj.name, "active_action": action.name}

    if method == "push_down_action":
        object_name = params.get("object_name")
        obj = _require_object(object_name)

        if obj.animation_data is None or obj.animation_data.action is None:
            raise ValueError(f"Object {obj.name} has no active action")

        action = obj.animation_data.action
        track = obj.animation_data.nla_tracks.new()
        strip_start = int(bpy.context.scene.frame_current)
        strip = track.strips.new(action.name, strip_start, action)
        obj.animation_data.action = None

        return {
            "object_name": obj.name,
            "pushed_action": action.name,
            "track": track.name,
            "strip": strip.name,
        }

    if method == "clear_animation_data":
        object_name = params.get("object_name")
        obj = _require_object(object_name)
        obj.animation_data_clear()
        return {"object_name": obj.name, "cleared": True}

    if method == "duplicate_action":
        action_name = params.get("action_name")
        new_name = params.get("new_name")
        action = _require_action(action_name)

        if not isinstance(new_name, str) or not new_name:
            new_name = f"{action.name}_copy"

        copy = action.copy()
        copy.name = new_name
        return {"action": {"name": copy.name, "users": copy.users}}

    if method == "delete_action":
        action_name = params.get("action_name")
        force = bool(params.get("force", False))
        action = _require_action(action_name)

        if action.users > 0 and not force:
            raise ValueError(
                f"Action {action.name} has {action.users} users. Set force=true to remove."
            )

        if force:
            action.user_clear()
        bpy.data.actions.remove(action)
        return {"deleted_action": action_name}

    if method == "list_nla_tracks":
        object_name = params.get("object_name")
        obj = _require_object(object_name)
        if obj.animation_data is None:
            return {"object_name": obj.name, "tracks": [], "count": 0}

        tracks = []
        for track in obj.animation_data.nla_tracks:
            strips = [_serialize_nla_strip(strip) for strip in track.strips]
            tracks.append(
                {
                    "name": track.name,
                    "mute": bool(track.mute),
                    "is_solo": bool(track.is_solo),
                    "strips": strips,
                }
            )
        return {"object_name": obj.name, "tracks": tracks, "count": len(tracks)}

    if method == "create_nla_strip":
        object_name = params.get("object_name")
        action_name = params.get("action_name")
        track_name = params.get("track_name")
        strip_name = params.get("strip_name")
        frame_start = params.get("frame_start")

        obj = _require_object(object_name)
        action = _require_action(action_name)
        if obj.animation_data is None:
            obj.animation_data_create()

        if isinstance(track_name, str) and track_name:
            track = obj.animation_data.nla_tracks.get(track_name)
            if track is None:
                track = obj.animation_data.nla_tracks.new()
                track.name = track_name
        else:
            track = obj.animation_data.nla_tracks.new()

        if not isinstance(frame_start, (int, float)):
            frame_start = float(bpy.context.scene.frame_current)

        new_strip_name = strip_name if isinstance(strip_name, str) and strip_name else action.name
        strip = track.strips.new(new_strip_name, int(frame_start), action)

        return {
            "object_name": obj.name,
            "track_name": track.name,
            "strip": _serialize_nla_strip(strip),
        }

    if method == "set_nla_strip":
        object_name = params.get("object_name")
        track_name = params.get("track_name")
        strip_name = params.get("strip_name")

        obj = _require_object(object_name)
        track = _require_nla_track(obj, track_name)
        strip = _require_nla_strip(track, strip_name)

        if "frame_start" in params and isinstance(params["frame_start"], (int, float)):
            strip.frame_start = float(params["frame_start"])
        if "frame_end" in params and isinstance(params["frame_end"], (int, float)):
            strip.frame_end = float(params["frame_end"])
        if "action_frame_start" in params and isinstance(
            params["action_frame_start"], (int, float)
        ):
            strip.action_frame_start = float(params["action_frame_start"])
        if "action_frame_end" in params and isinstance(params["action_frame_end"], (int, float)):
            strip.action_frame_end = float(params["action_frame_end"])
        if "scale" in params and isinstance(params["scale"], (int, float)):
            strip.scale = float(params["scale"])
        if "repeat" in params and isinstance(params["repeat"], (int, float)):
            strip.repeat = float(params["repeat"])
        if "mute" in params and isinstance(params["mute"], bool):
            strip.mute = params["mute"]

        return {
            "object_name": obj.name,
            "track_name": track.name,
            "strip": _serialize_nla_strip(strip),
        }

    if method == "remove_nla_strip":
        object_name = params.get("object_name")
        track_name = params.get("track_name")
        strip_name = params.get("strip_name")

        obj = _require_object(object_name)
        track = _require_nla_track(obj, track_name)
        strip = _require_nla_strip(track, strip_name)
        track.strips.remove(strip)
        return {"object_name": obj.name, "track_name": track.name, "removed_strip": strip_name}

    if method == "create_geometry_nodes_modifier":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")

        obj = _require_object(object_name)
        if not isinstance(modifier_name, str) or not modifier_name:
            raise ValueError("modifier_name must be a non-empty string")

        modifier = obj.modifiers.get(modifier_name)
        if modifier is None:
            modifier = obj.modifiers.new(name=modifier_name, type="NODES")
        elif modifier.type != "NODES":
            raise ValueError(
                f"Modifier {modifier_name} exists but is not a geometry nodes modifier"
            )

        node_group = _ensure_geometry_nodes_group(modifier)
        return {
            "object_name": obj.name,
            "modifier": {"name": modifier.name, "type": modifier.type},
            "node_group": node_group.name,
        }

    if method == "list_geometry_nodes":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        obj = _require_object(object_name)
        modifier = _require_modifier(obj, modifier_name)

        if modifier.type != "NODES" or modifier.node_group is None:
            raise ValueError(
                f"Modifier {modifier.name} is not configured with a geometry node tree"
            )

        node_group = modifier.node_group
        nodes = [{"name": node.name, "type": node.bl_idname} for node in node_group.nodes]
        links = []
        for link in node_group.links:
            links.append(
                {
                    "from_node": link.from_node.name,
                    "from_socket": link.from_socket.name,
                    "to_node": link.to_node.name,
                    "to_socket": link.to_socket.name,
                }
            )

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "node_group": node_group.name,
            "nodes": nodes,
            "links": links,
        }

    if method == "add_geometry_node":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        node_type = params.get("node_type")
        node_name = params.get("node_name")

        obj = _require_object(object_name)
        modifier = _require_modifier(obj, modifier_name)

        if modifier.type != "NODES":
            raise ValueError(f"Modifier {modifier.name} is not a geometry nodes modifier")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError("node_type must be a non-empty string")

        node_group = _ensure_geometry_nodes_group(modifier)
        node = node_group.nodes.new(node_type)
        if isinstance(node_name, str) and node_name:
            node.name = node_name

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "node": {"name": node.name, "type": node.bl_idname},
        }

    if method == "link_geometry_nodes":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        from_node_name = params.get("from_node")
        from_socket_name = params.get("from_socket")
        to_node_name = params.get("to_node")
        to_socket_name = params.get("to_socket")

        obj = _require_object(object_name)
        modifier = _require_modifier(obj, modifier_name)
        if modifier.type != "NODES":
            raise ValueError(f"Modifier {modifier.name} is not a geometry nodes modifier")

        for field_name, value in (
            ("from_node", from_node_name),
            ("from_socket", from_socket_name),
            ("to_node", to_node_name),
            ("to_socket", to_socket_name),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")

        node_group = _ensure_geometry_nodes_group(modifier)
        from_node = node_group.nodes.get(from_node_name)
        to_node = node_group.nodes.get(to_node_name)
        if from_node is None:
            raise ValueError(f"Node not found: {from_node_name}")
        if to_node is None:
            raise ValueError(f"Node not found: {to_node_name}")

        from_socket = from_node.outputs.get(from_socket_name)
        to_socket = to_node.inputs.get(to_socket_name)
        if from_socket is None:
            raise ValueError(f"Socket not found: {from_node_name}.{from_socket_name}")
        if to_socket is None:
            raise ValueError(f"Socket not found: {to_node_name}.{to_socket_name}")

        node_group.links.new(from_socket, to_socket)
        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "linked": {
                "from_node": from_node.name,
                "from_socket": from_socket.name,
                "to_node": to_node.name,
                "to_socket": to_socket.name,
            },
        }

    if method == "add_geometry_input":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        input_name = params.get("input_name")
        socket_type = params.get("socket_type", "NodeSocketFloat")
        default_value = params.get("default_value")

        obj = _require_object(object_name)
        modifier = _require_modifier(obj, modifier_name)
        if modifier.type != "NODES":
            raise ValueError(f"Modifier {modifier.name} is not a geometry nodes modifier")
        if not isinstance(input_name, str) or not input_name:
            raise ValueError("input_name must be a non-empty string")
        if not isinstance(socket_type, str) or not socket_type:
            raise ValueError("socket_type must be a non-empty string")

        node_group = _ensure_geometry_nodes_group(modifier)
        if hasattr(node_group, "interface"):
            socket = node_group.interface.new_socket(
                name=input_name,
                in_out="INPUT",
                socket_type=socket_type,
            )
            identifier = socket.identifier
            resolved_socket_type = socket.socket_type
        else:
            socket = node_group.inputs.new(socket_type, input_name)
            identifier = socket.identifier if hasattr(socket, "identifier") else socket.name
            resolved_socket_type = (
                socket.bl_socket_idname if hasattr(socket, "bl_socket_idname") else socket_type
            )

        if default_value is not None:
            stored_value: Any
            if isinstance(default_value, list):
                stored_value = tuple(default_value)
            else:
                stored_value = default_value
            modifier[identifier] = stored_value

        current = modifier.get(identifier)
        if hasattr(current, "__iter__") and not isinstance(current, (str, bytes, dict)):
            try:
                current = list(current)
            except TypeError:
                pass

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "input": {
                "name": input_name,
                "identifier": identifier,
                "socket_type": resolved_socket_type,
                "value": current,
            },
        }

    if method == "list_geometry_inputs":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        obj = _require_object(object_name)
        modifier = _require_modifier(obj, modifier_name)

        if modifier.type != "NODES" or modifier.node_group is None:
            raise ValueError(
                f"Modifier {modifier.name} is not configured with a geometry node tree"
            )

        inputs = []
        if hasattr(modifier.node_group, "interface"):
            for item in modifier.node_group.interface.items_tree:
                if item.item_type != "SOCKET" or item.in_out != "INPUT":
                    continue

                identifier = item.identifier
                value: Any = modifier.get(identifier)
                if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
                    try:
                        value = list(value)
                    except TypeError:
                        pass

                use_attr_key = f"{identifier}_use_attribute"
                attr_name_key = f"{identifier}_attribute_name"
                inputs.append(
                    {
                        "name": item.name,
                        "identifier": identifier,
                        "socket_type": item.socket_type,
                        "value": value,
                        "use_attribute": bool(modifier.get(use_attr_key, False)),
                        "attribute_name": modifier.get(attr_name_key, ""),
                    }
                )
        else:
            for socket in modifier.node_group.inputs:
                identifier = socket.identifier if hasattr(socket, "identifier") else socket.name
                value = modifier.get(identifier)
                if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
                    try:
                        value = list(value)
                    except TypeError:
                        pass
                use_attr_key = f"{identifier}_use_attribute"
                attr_name_key = f"{identifier}_attribute_name"
                inputs.append(
                    {
                        "name": socket.name,
                        "identifier": identifier,
                        "socket_type": getattr(socket, "bl_socket_idname", "UNKNOWN"),
                        "value": value,
                        "use_attribute": bool(modifier.get(use_attr_key, False)),
                        "attribute_name": modifier.get(attr_name_key, ""),
                    }
                )

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "inputs": inputs,
            "count": len(inputs),
        }

    if method == "set_geometry_input":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        input_ref = params.get("input_name_or_identifier")
        value = params.get("value")
        use_attribute = params.get("use_attribute")
        attribute_name = params.get("attribute_name")

        obj = _require_object(object_name)
        modifier = _require_modifier(obj, modifier_name)
        if modifier.type != "NODES" or modifier.node_group is None:
            raise ValueError(
                f"Modifier {modifier.name} is not configured with a geometry node tree"
            )

        identifier, input_name = _resolve_geometry_input_identifier(modifier.node_group, input_ref)

        if isinstance(value, list):
            cast_value: Any = tuple(value)
        else:
            cast_value = value

        if value is not None:
            modifier[identifier] = cast_value

        use_attr_key = f"{identifier}_use_attribute"
        attr_name_key = f"{identifier}_attribute_name"
        if isinstance(use_attribute, bool):
            modifier[use_attr_key] = use_attribute
        if isinstance(attribute_name, str):
            modifier[attr_name_key] = attribute_name

        current: Any = modifier.get(identifier)
        if hasattr(current, "__iter__") and not isinstance(current, (str, bytes, dict)):
            try:
                current = list(current)
            except TypeError:
                pass

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "input": {
                "name": input_name,
                "identifier": identifier,
                "value": current,
                "use_attribute": bool(modifier.get(use_attr_key, False)),
                "attribute_name": modifier.get(attr_name_key, ""),
            },
        }

    if method == "add_modifier":
        obj = _require_object(params.get("object_name"))
        modifier_type = params.get("modifier_type")
        name = params.get("name")

        if not isinstance(modifier_type, str) or not modifier_type:
            raise ValueError("modifier_type must be a non-empty string")

        modifier_name = name if isinstance(name, str) and name else modifier_type.title()
        modifier = obj.modifiers.new(name=modifier_name, type=modifier_type.upper())

        settings = params.get("settings")
        if isinstance(settings, dict):
            for key, value in settings.items():
                if hasattr(modifier, key):
                    setattr(modifier, key, value)

        return {
            "object_name": obj.name,
            "modifier": {"name": modifier.name, "type": modifier.type},
            "modifiers_total": len(obj.modifiers),
        }

    if method == "list_modifiers":
        obj = _require_object(params.get("object_name"))
        modifiers = [{"name": mod.name, "type": mod.type} for mod in obj.modifiers]
        return {"object_name": obj.name, "modifiers": modifiers, "count": len(modifiers)}

    if method == "apply_modifier":
        obj = _require_object(params.get("object_name"))
        modifier_name = params.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            raise ValueError("modifier_name must be a non-empty string")

        if obj.modifiers.get(modifier_name) is None:
            raise ValueError(f"Modifier not found: {modifier_name}")

        _set_active_object(obj)
        bpy.ops.object.modifier_apply(modifier=modifier_name)
        return {"object_name": obj.name, "applied_modifier": modifier_name}

    if method == "remove_modifier":
        obj = _require_object(params.get("object_name"))
        modifier_name = params.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            raise ValueError("modifier_name must be a non-empty string")

        modifier = obj.modifiers.get(modifier_name)
        if modifier is None:
            raise ValueError(f"Modifier not found: {modifier_name}")

        obj.modifiers.remove(modifier)
        return {"object_name": obj.name, "removed_modifier": modifier_name}

    if method == "add_constraint":
        obj = _require_object(params.get("object_name"))
        constraint_type = params.get("constraint_type")
        constraint_name = params.get("name")
        target_name = params.get("target_name")

        if not isinstance(constraint_type, str) or not constraint_type:
            raise ValueError("constraint_type must be a non-empty string")

        constraint = obj.constraints.new(type=constraint_type.upper())
        if isinstance(constraint_name, str) and constraint_name:
            constraint.name = constraint_name

        if isinstance(target_name, str) and target_name:
            target = _require_object(target_name)
            if hasattr(constraint, "target"):
                constraint.target = target

        return {
            "object_name": obj.name,
            "constraint": {"name": constraint.name, "type": constraint.type},
            "constraints_total": len(obj.constraints),
        }

    if method == "list_constraints":
        obj = _require_object(params.get("object_name"))
        constraints = []
        for constraint in obj.constraints:
            constraints.append(
                {
                    "name": constraint.name,
                    "type": constraint.type,
                    "target": constraint.target.name
                    if hasattr(constraint, "target") and constraint.target is not None
                    else None,
                }
            )
        return {"object_name": obj.name, "constraints": constraints, "count": len(constraints)}

    if method == "remove_constraint":
        obj = _require_object(params.get("object_name"))
        constraint_name = params.get("constraint_name")
        if not isinstance(constraint_name, str) or not constraint_name:
            raise ValueError("constraint_name must be a non-empty string")

        constraint = obj.constraints.get(constraint_name)
        if constraint is None:
            raise ValueError(f"Constraint not found: {constraint_name}")

        obj.constraints.remove(constraint)
        return {"object_name": obj.name, "removed_constraint": constraint_name}

    if method == "create_material":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        base_color_raw = params.get("base_color", [0.8, 0.8, 0.8, 1.0])
        if not isinstance(base_color_raw, list) or len(base_color_raw) != 4:
            raise ValueError("base_color must be a list of 4 numbers")

        base_color = [float(v) for v in base_color_raw]
        roughness = float(params.get("roughness", 0.5))
        metallic = float(params.get("metallic", 0.0))

        material = bpy.data.materials.get(name)
        if material is None:
            material = bpy.data.materials.new(name=name)

        material.use_nodes = True
        nodes = material.node_tree.nodes
        principled = nodes.get("Principled BSDF")
        if principled is None:
            raise RuntimeError("Principled BSDF node not found")

        principled.inputs["Base Color"].default_value = base_color
        principled.inputs["Roughness"].default_value = roughness
        principled.inputs["Metallic"].default_value = metallic

        return {
            "material": {
                "name": material.name,
                "base_color": base_color,
                "roughness": roughness,
                "metallic": metallic,
            }
        }

    if method == "assign_material":
        object_name = params.get("object_name")
        material_name = params.get("material_name")

        obj = _require_object(object_name)
        if not isinstance(material_name, str) or not material_name:
            raise ValueError("material_name must be a non-empty string")

        material = bpy.data.materials.get(material_name)
        if material is None:
            raise ValueError(f"Material not found: {material_name}")

        if not hasattr(obj.data, "materials"):
            raise ValueError(f"Object type {obj.type} does not support materials")

        slot_index = params.get("slot_index")
        materials = obj.data.materials

        if isinstance(slot_index, int) and slot_index >= 0 and slot_index < len(materials):
            materials[slot_index] = material
        else:
            materials.append(material)

        return {"object": _serialize_object(obj)}

    if method == "create_camera":
        name = params.get("name", "Camera")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        location = _to_vector3(params.get("location", [0.0, -6.0, 3.0]), "location")
        rotation = _to_vector3(params.get("rotation", [1.1, 0.0, 0.0]), "rotation")
        set_active = bool(params.get("set_active", True))

        camera_data = bpy.data.cameras.new(f"{name}Data")
        camera_object = bpy.data.objects.new(name, camera_data)
        bpy.context.scene.collection.objects.link(camera_object)

        camera_object.location = location
        camera_object.rotation_euler = rotation

        if set_active:
            bpy.context.scene.camera = camera_object

        return {
            "object": _serialize_object(camera_object),
            "active_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
        }

    if method == "set_active_camera":
        camera = _require_object(params.get("name"))
        if camera.type != "CAMERA":
            raise ValueError(f"Object '{camera.name}' is not a camera")

        bpy.context.scene.camera = camera
        return {"active_camera": camera.name}

    if method == "create_light":
        name = params.get("name", "Light")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        light_type = params.get("light_type", "POINT")
        if not isinstance(light_type, str):
            raise ValueError("light_type must be a string")

        light_type = light_type.upper()
        allowed = {"POINT", "SUN", "SPOT", "AREA"}
        if light_type not in allowed:
            raise ValueError(f"Unsupported light_type {light_type}. Allowed: {sorted(allowed)}")

        energy = float(params.get("energy", 1000.0))
        location = _to_vector3(params.get("location", [4.0, -4.0, 6.0]), "location")
        rotation = _to_vector3(params.get("rotation", [0.6, 0.0, 0.8]), "rotation")

        light_data = bpy.data.lights.new(name=f"{name}Data", type=light_type)
        light_data.energy = energy

        light_object = bpy.data.objects.new(name, light_data)
        bpy.context.scene.collection.objects.link(light_object)
        light_object.location = location
        light_object.rotation_euler = rotation

        return {"object": _serialize_object(light_object)}

    if method == "enable_compositor":
        scene = bpy.context.scene
        use_nodes = bool(params.get("use_nodes", True))
        clear_nodes = bool(params.get("clear_nodes", False))
        if hasattr(scene, "use_nodes"):
            scene.use_nodes = use_nodes

        node_tree = _get_or_create_compositor_tree(scene)

        if clear_nodes:
            node_tree.nodes.clear()
            render_layers = node_tree.nodes.new("CompositorNodeRLayers")
            if "Image" in render_layers.outputs:
                output = node_tree.nodes.new("CompositorNodeOutputFile")
                node_tree.links.new(render_layers.outputs["Image"], output.inputs[0])

        return {
            "use_nodes": bool(getattr(scene, "use_nodes", use_nodes)),
            "nodes_total": len(node_tree.nodes),
        }

    if method == "list_compositor_nodes":
        scene = bpy.context.scene
        node_tree = _require_node_tree(scene)
        nodes = [{"name": node.name, "type": node.bl_idname} for node in node_tree.nodes]
        links = []
        for link in node_tree.links:
            links.append(
                {
                    "from_node": link.from_node.name,
                    "from_socket": link.from_socket.name,
                    "to_node": link.to_node.name,
                    "to_socket": link.to_socket.name,
                }
            )
        return {"nodes": nodes, "links": links, "count": len(nodes)}

    if method == "add_compositor_node":
        scene = bpy.context.scene
        node_tree = _require_node_tree(scene)

        node_type = params.get("node_type")
        node_name = params.get("node_name")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError("node_type must be a non-empty string")

        node = node_tree.nodes.new(node_type)
        if isinstance(node_name, str) and node_name:
            node.name = node_name

        return {"node": {"name": node.name, "type": node.bl_idname}}

    if method == "link_compositor_nodes":
        scene = bpy.context.scene
        node_tree = _require_node_tree(scene)

        from_node_name = params.get("from_node")
        from_socket_name = params.get("from_socket")
        to_node_name = params.get("to_node")
        to_socket_name = params.get("to_socket")

        for field_name, value in (
            ("from_node", from_node_name),
            ("from_socket", from_socket_name),
            ("to_node", to_node_name),
            ("to_socket", to_socket_name),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")

        from_node = node_tree.nodes.get(from_node_name)
        to_node = node_tree.nodes.get(to_node_name)
        if from_node is None:
            raise ValueError(f"Node not found: {from_node_name}")
        if to_node is None:
            raise ValueError(f"Node not found: {to_node_name}")

        from_socket = from_node.outputs.get(from_socket_name)
        to_socket = to_node.inputs.get(to_socket_name)
        if from_socket is None:
            raise ValueError(f"Socket not found: {from_node_name}.{from_socket_name}")
        if to_socket is None:
            raise ValueError(f"Socket not found: {to_node_name}.{to_socket_name}")

        node_tree.links.new(from_socket, to_socket)
        return {
            "linked": {
                "from_node": from_node.name,
                "from_socket": from_socket.name,
                "to_node": to_node.name,
                "to_socket": to_socket.name,
            }
        }

    if method == "set_view_layer_passes":
        view_layer_name = params.get("view_layer_name")
        resolved_view_layer_name = view_layer_name if isinstance(view_layer_name, str) else None
        view_layer = _require_view_layer(resolved_view_layer_name)

        requested_passes = {
            "use_pass_z": params.get("use_pass_z"),
            "use_pass_normal": params.get("use_pass_normal"),
            "use_pass_vector": params.get("use_pass_vector"),
            "use_pass_diffuse_color": params.get("use_pass_diffuse_color"),
            "use_pass_glossy_color": params.get("use_pass_glossy_color"),
            "use_pass_emit": params.get("use_pass_emit"),
            "use_pass_ambient_occlusion": params.get("use_pass_ambient_occlusion"),
        }

        applied: dict[str, bool] = {}
        unsupported: list[str] = []
        for attr_name, raw_value in requested_passes.items():
            if not isinstance(raw_value, bool):
                continue

            if hasattr(view_layer, attr_name):
                setattr(view_layer, attr_name, raw_value)
                applied[attr_name] = bool(getattr(view_layer, attr_name))
            else:
                unsupported.append(attr_name)

        return {
            "view_layer_name": view_layer.name,
            "applied": applied,
            "unsupported": unsupported,
        }

    if method == "set_viewport_view":
        if bpy.app.background:
            raise ValueError("Viewport view controls are unavailable in background mode")

        context = _find_view3d_context()
        if context is None:
            raise ValueError("No VIEW_3D viewport context available (likely headless mode)")

        window, area, region, space, region_3d = context
        view = params.get("view")
        location = params.get("location")
        rotation_quaternion = params.get("rotation_quaternion")
        distance = params.get("distance")
        lens = params.get("lens")
        shading_type = params.get("shading_type")

        if isinstance(view, str) and view:
            view_upper = view.upper()
            with bpy.context.temp_override(window=window, area=area, region=region):
                if view_upper in {"FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"}:
                    bpy.ops.view3d.view_axis(type=view_upper, align_active=False)
                elif view_upper == "CAMERA":
                    bpy.ops.view3d.view_camera()
                elif view_upper == "PERSP":
                    region_3d.view_perspective = "PERSP"
                elif view_upper == "ORTHO":
                    region_3d.view_perspective = "ORTHO"
                else:
                    raise ValueError(
                        "view must be one of FRONT/BACK/LEFT/RIGHT/TOP/BOTTOM/CAMERA/PERSP/ORTHO"
                    )

        if "location" in params:
            region_3d.view_location = _to_vector3(location, "location")
        if "rotation_quaternion" in params:
            region_3d.view_rotation = Quaternion(
                _to_quaternion(rotation_quaternion, "rotation_quaternion")
            )
        if isinstance(distance, (int, float)):
            region_3d.view_distance = float(distance)
        if isinstance(lens, (int, float)):
            space.lens = float(lens)
        if isinstance(shading_type, str) and hasattr(space, "shading"):
            space.shading.type = shading_type.upper()

        return {
            "view_perspective": region_3d.view_perspective,
            "view_location": [float(v) for v in region_3d.view_location],
            "view_distance": float(region_3d.view_distance),
            "view_rotation": [float(v) for v in region_3d.view_rotation],
            "lens": float(space.lens),
            "shading_type": space.shading.type if hasattr(space, "shading") else None,
        }

    if method == "capture_viewport_screenshot":
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

    if method == "workflow_setup_studio":
        object_name = params.get("object_name", "Subject")
        primitive = params.get("primitive", "CUBE")
        add_ground = bool(params.get("add_ground", True))
        camera_name = params.get("camera_name", "WorkflowCamera")
        key_energy = float(params.get("key_energy", 1200.0))
        fill_energy = float(params.get("fill_energy", 600.0))
        rim_energy = float(params.get("rim_energy", 900.0))
        camera_distance = float(params.get("camera_distance", 6.0))
        camera_height = float(params.get("camera_height", 3.0))

        if not isinstance(object_name, str) or not object_name:
            raise ValueError("object_name must be a non-empty string")
        if not isinstance(primitive, str) or not primitive:
            raise ValueError("primitive must be a non-empty string")
        if not isinstance(camera_name, str) or not camera_name:
            raise ValueError("camera_name must be a non-empty string")

        subject = _ensure_subject_object(
            object_name=object_name,
            primitive=primitive,
            size=float(params.get("size", 2.0)),
        )

        target = Vector(subject.location)
        camera_location = target + Vector((0.0, -camera_distance, camera_height))
        camera = bpy.data.objects.get(camera_name)
        if camera is None or camera.type != "CAMERA":
            camera_data = bpy.data.cameras.new(f"{camera_name}Data")
            camera = bpy.data.objects.new(camera_name, camera_data)
            bpy.context.scene.collection.objects.link(camera)
        camera.location = camera_location
        direction = target - camera.location
        if direction.length > 0:
            camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.camera = camera

        key = _create_or_update_light(
            name="WorkflowKeyLight",
            light_type="AREA",
            energy=key_energy,
            location=tuple(
                target + Vector((camera_distance * 0.8, -camera_distance * 0.8, camera_height))
            ),
        )
        fill = _create_or_update_light(
            name="WorkflowFillLight",
            light_type="AREA",
            energy=fill_energy,
            location=tuple(
                target
                + Vector((-camera_distance * 0.8, -camera_distance * 0.5, camera_height * 0.7))
            ),
        )
        rim = _create_or_update_light(
            name="WorkflowRimLight",
            light_type="AREA",
            energy=rim_energy,
            location=tuple(target + Vector((0.0, camera_distance * 0.9, camera_height))),
        )

        ground_name = "WorkflowGround"
        if add_ground:
            ground = bpy.data.objects.get(ground_name)
            if ground is None:
                bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 0.0, 0.0))
                ground = bpy.context.active_object
                if ground is not None:
                    ground.name = ground_name
            if ground is not None:
                ground.location.z = float(subject.location.z - subject.dimensions.z * 0.5)

        return {
            "subject": _serialize_object(subject),
            "camera": _serialize_object(camera),
            "lights": [key.name, fill.name, rim.name],
            "ground": ground_name if add_ground else None,
        }

    if method == "workflow_create_turntable":
        object_name = params.get("object_name")
        frame_start = int(params.get("frame_start", 1))
        frame_end = int(params.get("frame_end", 120))
        rotations = float(params.get("rotations", 1.0))
        axis = params.get("axis", "Z")

        obj = _require_object(object_name)
        if not isinstance(axis, str) or axis.upper() not in {"X", "Y", "Z"}:
            raise ValueError("axis must be one of X, Y, Z")

        axis_index = {"X": 0, "Y": 1, "Z": 2}[axis.upper()]
        scene = bpy.context.scene
        scene.frame_start = frame_start
        scene.frame_end = frame_end

        start_rotation = [float(v) for v in obj.rotation_euler]
        end_rotation = start_rotation.copy()
        end_rotation[axis_index] = start_rotation[axis_index] + (2.0 * math.pi * rotations)

        scene.frame_set(frame_start)
        obj.rotation_euler = tuple(start_rotation)
        obj.keyframe_insert(data_path="rotation_euler", frame=frame_start)
        scene.frame_set(frame_end)
        obj.rotation_euler = tuple(end_rotation)
        obj.keyframe_insert(data_path="rotation_euler", frame=frame_end)

        action_name: str | None = None
        if obj.animation_data is not None and obj.animation_data.action is not None:
            action_name = obj.animation_data.action.name
        return {
            "object_name": obj.name,
            "axis": axis.upper(),
            "rotations": rotations,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "action": action_name,
        }

    if method == "workflow_turntable_render":
        object_name = params.get("object_name", "Subject")
        output_path = _normalize_path(params.get("output_path"), require_exists=False)
        frame_start = int(params.get("frame_start", 1))
        frame_end = int(params.get("frame_end", 120))
        resolution_x = int(params.get("resolution_x", 512))
        resolution_y = int(params.get("resolution_y", 512))
        setup_studio = bool(params.get("setup_studio", True))

        if setup_studio:
            _dispatch_command(
                "workflow_setup_studio",
                {
                    "object_name": object_name,
                    "primitive": params.get("primitive", "CUBE"),
                    "add_ground": params.get("add_ground", True),
                    "size": params.get("size", 2.0),
                },
            )

        _dispatch_command(
            "workflow_create_turntable",
            {
                "object_name": object_name,
                "frame_start": frame_start,
                "frame_end": frame_end,
                "rotations": params.get("rotations", 1.0),
                "axis": params.get("axis", "Z"),
            },
        )

        scene = bpy.context.scene
        engine = params.get("engine")
        if isinstance(engine, str) and engine:
            scene.render.engine = engine
        scene.render.resolution_x = resolution_x
        scene.render.resolution_y = resolution_y
        if (
            isinstance(params.get("samples"), int)
            and params.get("samples") > 0
            and hasattr(scene, "cycles")
        ):
            scene.cycles.samples = int(params.get("samples"))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = output_path
        bpy.ops.render.render(animation=True)
        return {
            "rendered": True,
            "object_name": object_name,
            "filepath": output_path,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "engine": scene.render.engine,
        }

    if method == "render_still":
        filepath = _normalize_path(params.get("filepath"), require_exists=False)
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        scene = bpy.context.scene
        engine = params.get("engine")
        if isinstance(engine, str) and engine:
            scene.render.engine = engine

        resolution_x = params.get("resolution_x")
        resolution_y = params.get("resolution_y")
        if isinstance(resolution_x, int) and resolution_x > 0:
            scene.render.resolution_x = resolution_x
        if isinstance(resolution_y, int) and resolution_y > 0:
            scene.render.resolution_y = resolution_y

        samples = params.get("samples")
        if isinstance(samples, int) and samples > 0 and hasattr(scene, "cycles"):
            scene.cycles.samples = samples

        scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True)
        return {"rendered": True, "filepath": filepath, "engine": scene.render.engine}

    if method == "render_animation":
        filepath = _normalize_path(params.get("filepath"), require_exists=False)
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        scene = bpy.context.scene
        engine = params.get("engine")
        frame_start = params.get("frame_start")
        frame_end = params.get("frame_end")

        if isinstance(engine, str) and engine:
            scene.render.engine = engine
        if isinstance(frame_start, int):
            scene.frame_start = frame_start
        if isinstance(frame_end, int):
            scene.frame_end = frame_end

        scene.render.filepath = filepath
        bpy.ops.render.render(animation=True)
        return {
            "rendered": True,
            "filepath": filepath,
            "engine": scene.render.engine,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        }

    if method == "import_file":
        filepath = _normalize_path(params.get("filepath"), require_exists=True)
        file_type = _resolve_file_type(filepath, params.get("file_type"))

        if file_type == "OBJ":
            bpy.ops.wm.obj_import(filepath=filepath)
        elif file_type == "FBX":
            bpy.ops.import_scene.fbx(filepath=filepath)
        elif file_type == "GLTF":
            bpy.ops.import_scene.gltf(filepath=filepath)
        else:
            bpy.ops.wm.usd_import(filepath=filepath)

        objects_total = len(bpy.context.scene.objects)
        return {
            "imported": True,
            "file_type": file_type,
            "objects_total": objects_total,
        }

    if method == "export_file":
        filepath = _normalize_path(params.get("filepath"), require_exists=False)
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        file_type = _resolve_file_type(filepath, params.get("file_type"))
        use_selection = bool(params.get("use_selection", False))

        if file_type == "OBJ":
            bpy.ops.wm.obj_export(filepath=filepath, export_selected_objects=use_selection)
        elif file_type == "FBX":
            bpy.ops.export_scene.fbx(filepath=filepath, use_selection=use_selection)
        elif file_type == "GLTF":
            bpy.ops.export_scene.gltf(filepath=filepath, export_selected=use_selection)
        else:
            bpy.ops.wm.usd_export(filepath=filepath, selected_objects_only=use_selection)

        return {"exported": True, "file_type": file_type, "filepath": filepath}

    if method == "list_collections":
        collections = [
            {"name": collection.name, "objects_total": len(collection.objects)}
            for collection in bpy.data.collections
        ]
        return {"collections": collections, "count": len(collections)}

    if method == "create_collection":
        name = params.get("name")
        parent_name = params.get("parent_name")
        link_to_scene = bool(params.get("link_to_scene", True))

        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        if bpy.data.collections.get(name) is not None:
            raise ValueError(f"Collection already exists: {name}")

        collection = bpy.data.collections.new(name)
        if isinstance(parent_name, str) and parent_name:
            parent = _require_collection(parent_name)
            parent.children.link(collection)
        elif link_to_scene:
            bpy.context.scene.collection.children.link(collection)

        return {"collection": {"name": collection.name, "objects_total": len(collection.objects)}}

    if method == "add_object_to_collection":
        object_name = params.get("object_name")
        collection_name = params.get("collection_name")
        unlink_from_others = bool(params.get("unlink_from_others", False))

        obj = _require_object(object_name)
        collection = _require_collection(collection_name)

        if obj.name not in collection.objects:
            collection.objects.link(obj)

        if unlink_from_others:
            for candidate in bpy.data.collections:
                if candidate.name != collection.name and obj.name in candidate.objects:
                    candidate.objects.unlink(obj)

        return {
            "object_name": obj.name,
            "collection_name": collection.name,
            "unlink_from_others": unlink_from_others,
        }

    if method == "remove_object_from_collection":
        object_name = params.get("object_name")
        collection_name = params.get("collection_name")
        obj = _require_object(object_name)
        collection = _require_collection(collection_name)

        if obj.name not in collection.objects:
            raise ValueError(f"Object {obj.name} is not linked to collection {collection.name}")

        collection.objects.unlink(obj)
        return {"object_name": obj.name, "collection_name": collection.name}

    if method == "list_view_layers":
        scene = bpy.context.scene
        active = bpy.context.view_layer.name
        layers = [{"name": view_layer.name} for view_layer in scene.view_layers]
        return {"view_layers": layers, "active_view_layer": active, "count": len(layers)}

    if method == "set_active_view_layer":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        view_layer = _require_view_layer(name)
        window = bpy.context.window
        if window is None:
            raise RuntimeError("No active window available to set view layer")
        window.view_layer = view_layer
        return {"active_view_layer": view_layer.name}

    if method == "set_collection_visibility":
        collection_name = params.get("collection_name")
        collection = _require_collection(collection_name)
        view_layer_name = params.get("view_layer_name")
        resolved_view_layer_name = view_layer_name if isinstance(view_layer_name, str) else None
        view_layer = _require_view_layer(resolved_view_layer_name)

        hide_viewport = params.get("hide_viewport")
        hide_render = params.get("hide_render")
        exclude = params.get("exclude")
        holdout = params.get("holdout")
        indirect_only = params.get("indirect_only")

        if isinstance(hide_viewport, bool):
            collection.hide_viewport = hide_viewport
        if isinstance(hide_render, bool):
            collection.hide_render = hide_render

        layer_collection = _find_layer_collection(view_layer.layer_collection, collection.name)
        if layer_collection is None:
            raise ValueError(
                f"Collection {collection.name} is not present in view layer {view_layer.name}"
            )

        if isinstance(exclude, bool):
            layer_collection.exclude = exclude
        if isinstance(holdout, bool):
            layer_collection.holdout = holdout
        if isinstance(indirect_only, bool):
            layer_collection.indirect_only = indirect_only

        return {
            "collection_name": collection.name,
            "view_layer_name": view_layer.name,
            "hide_viewport": collection.hide_viewport,
            "hide_render": collection.hide_render,
            "exclude": layer_collection.exclude,
            "holdout": layer_collection.holdout,
            "indirect_only": layer_collection.indirect_only,
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
    return [
        "health",
        "new_scene",
        "open_blend",
        "save_blend",
        "get_scene_info",
        "set_timeline",
        "list_objects",
        "get_object_info",
        "create_primitive",
        "delete_object",
        "set_object_transform",
        "duplicate_object",
        "keyframe_transform",
        "insert_keyframe",
        "list_animation_data",
        "list_actions",
        "create_action",
        "set_active_action",
        "push_down_action",
        "clear_animation_data",
        "duplicate_action",
        "delete_action",
        "list_nla_tracks",
        "create_nla_strip",
        "set_nla_strip",
        "remove_nla_strip",
        "create_geometry_nodes_modifier",
        "list_geometry_nodes",
        "add_geometry_node",
        "link_geometry_nodes",
        "add_geometry_input",
        "list_geometry_inputs",
        "set_geometry_input",
        "add_modifier",
        "list_modifiers",
        "apply_modifier",
        "remove_modifier",
        "add_constraint",
        "list_constraints",
        "remove_constraint",
        "create_material",
        "assign_material",
        "create_camera",
        "set_active_camera",
        "create_light",
        "enable_compositor",
        "list_compositor_nodes",
        "add_compositor_node",
        "link_compositor_nodes",
        "set_view_layer_passes",
        "set_viewport_view",
        "capture_viewport_screenshot",
        "workflow_setup_studio",
        "workflow_create_turntable",
        "workflow_turntable_render",
        "render_still",
        "render_animation",
        "import_file",
        "export_file",
        "list_collections",
        "create_collection",
        "add_object_to_collection",
        "remove_object_from_collection",
        "list_view_layers",
        "set_active_view_layer",
        "set_collection_visibility",
        "execute_code",
    ]


def _drain_command_queue() -> float | None:
    global _RUNTIME
    global _TIMER_REGISTERED

    if _RUNTIME is None or not _RUNTIME.running or _RUNTIME.command_queue is None:
        _TIMER_REGISTERED = False
        return None

    drained = 0
    max_per_tick = 25

    while drained < max_per_tick:
        try:
            command = _RUNTIME.command_queue.get_nowait()
        except queue.Empty:
            break

        try:
            result = _dispatch_command(command.method, command.params)
            response = {"id": command.request_id, "ok": True, "result": result}
        except Exception as exc:  # pylint: disable=broad-except
            response = {"id": command.request_id, "ok": False, "error": str(exc)}

        command.result_queue.put(response)
        drained += 1

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
        token=prefs.token,
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
) -> None:
    global _RUNTIME

    if _RUNTIME is not None and _RUNTIME.running:
        return

    runtime = BridgeRuntime(
        host=host,
        port=port,
        token=token,
        timeout_seconds=timeout_seconds,
        allow_unsafe_code=allow_unsafe_code,
        running=True,
        command_queue=queue.Queue(),
    )

    server = _BridgeTCPServer((runtime.host, runtime.port), _BridgeRequestHandler, runtime)
    thread = threading.Thread(
        target=server.serve_forever,
        name="better-blender-bridge",
        daemon=True,
    )
    runtime.server = server
    runtime.thread = thread

    _RUNTIME = runtime
    if register_timer:
        _register_timer_if_needed()
    thread.start()


def stop_bridge() -> None:
    global _RUNTIME

    if _RUNTIME is None:
        return

    runtime = _RUNTIME
    runtime.running = False

    if runtime.server is not None:
        runtime.server.shutdown()
        runtime.server.server_close()

    if runtime.thread is not None and runtime.thread.is_alive():
        runtime.thread.join(timeout=1.0)

    _RUNTIME = None


class BetterBlenderPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    host: bpy.props.StringProperty(name="Host", default="127.0.0.1")
    port: bpy.props.IntProperty(name="Port", default=8765, min=1024, max=65535)
    token: bpy.props.StringProperty(name="Token", default="change-me")
    timeout_seconds: bpy.props.FloatProperty(
        name="Request Timeout", default=30.0, min=1.0, max=300.0
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
        layout.prop(self, "allow_unsafe_code")


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
