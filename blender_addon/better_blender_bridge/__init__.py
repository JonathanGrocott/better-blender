"""Better Blender Bridge add-on.

This add-on exposes a local TCP JSON interface that the MCP server can call.
All bpy operations execute on Blender's main thread through a timer-drained queue.
"""

from __future__ import annotations

import json
import queue
import socketserver
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy

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

        fcurves = []
        for fcurve in animation_data.action.fcurves:
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
            "action": animation_data.action.name,
            "fcurves": fcurves,
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
        prefs = _get_addon_prefs()
        if not prefs.allow_unsafe_code:
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
        "render_still",
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
    global _RUNTIME

    if _RUNTIME is not None and _RUNTIME.running:
        return

    prefs = _get_addon_prefs(context)
    runtime = BridgeRuntime(
        host=prefs.host,
        port=prefs.port,
        token=prefs.token,
        timeout_seconds=prefs.timeout_seconds,
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
