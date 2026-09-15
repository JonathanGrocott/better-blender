"""Main-thread rendering commands. Shared validation and helpers come from the bridge context."""

from __future__ import annotations

import base64
import math
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

METHODS = frozenset(
    [
        "create_camera",
        "set_active_camera",
        "create_light",
        "set_view_layer_passes",
        "set_viewport_view",
        "capture_viewport_screenshot",
        "workflow_setup_studio",
        "workflow_create_turntable",
        "workflow_turntable_render",
        "render_still",
        "render_animation",
    ]
)


def dispatch(method, params, bridge):
    if method == "create_camera":
        name = params.get("name", "Camera")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        location = bridge._to_vector3(params.get("location", [0.0, -6.0, 3.0]), "location")
        rotation = bridge._to_vector3(params.get("rotation", [1.1, 0.0, 0.0]), "rotation")
        set_active = bool(params.get("set_active", True))

        camera_data = bpy.data.cameras.new(f"{name}Data")
        camera_object = bpy.data.objects.new(name, camera_data)
        bpy.context.scene.collection.objects.link(camera_object)

        camera_object.location = location
        camera_object.rotation_euler = rotation

        if set_active:
            bpy.context.scene.camera = camera_object

        return {
            "object": bridge._serialize_object(camera_object),
            "active_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
        }

    if method == "set_active_camera":
        camera = bridge._require_object(params.get("name"))
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
        location = bridge._to_vector3(params.get("location", [4.0, -4.0, 6.0]), "location")
        rotation = bridge._to_vector3(params.get("rotation", [0.6, 0.0, 0.8]), "rotation")

        light_data = bpy.data.lights.new(name=f"{name}Data", type=light_type)
        light_data.energy = energy

        light_object = bpy.data.objects.new(name, light_data)
        bpy.context.scene.collection.objects.link(light_object)
        light_object.location = location
        light_object.rotation_euler = rotation

        return {"object": bridge._serialize_object(light_object)}

    if method == "set_view_layer_passes":
        view_layer_name = params.get("view_layer_name")
        resolved_view_layer_name = view_layer_name if isinstance(view_layer_name, str) else None
        view_layer = bridge._require_view_layer(resolved_view_layer_name)

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

        context = bridge._find_view3d_context()
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
            region_3d.view_location = bridge._to_vector3(location, "location")
        if "rotation_quaternion" in params:
            region_3d.view_rotation = Quaternion(
                bridge._to_quaternion(rotation_quaternion, "rotation_quaternion")
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
        render = bpy.context.scene.render
        previous = (render.image_settings.file_format, render.resolution_percentage)
        render.image_settings.file_format = "PNG"
        render.resolution_percentage = 100
        params = {**params, "filepath": str(Path(params["filepath"]).with_suffix(".png"))}
        try:
            result = bridge._capture_viewport(params)
        finally:
            render.image_settings.file_format, render.resolution_percentage = previous
        path = Path(result["filepath"])
        if path.stat().st_size <= 8 * 1024 * 1024:
            result["image"] = {
                "mime_type": "image/png",
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        else:
            result["image_error"] = (
                "Image exceeds 8 MiB; reduce capture resolution for inline preview"
            )
        return result

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

        subject = bridge._ensure_subject_object(
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

        key = bridge._create_or_update_light(
            name="WorkflowKeyLight",
            light_type="AREA",
            energy=key_energy,
            location=tuple(
                target + Vector((camera_distance * 0.8, -camera_distance * 0.8, camera_height))
            ),
        )
        fill = bridge._create_or_update_light(
            name="WorkflowFillLight",
            light_type="AREA",
            energy=fill_energy,
            location=tuple(
                target
                + Vector((-camera_distance * 0.8, -camera_distance * 0.5, camera_height * 0.7))
            ),
        )
        rim = bridge._create_or_update_light(
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
            "subject": bridge._serialize_object(subject),
            "camera": bridge._serialize_object(camera),
            "lights": [key.name, fill.name, rim.name],
            "ground": ground_name if add_ground else None,
        }

    if method == "workflow_create_turntable":
        object_name = params.get("object_name")
        frame_start = int(params.get("frame_start", 1))
        frame_end = int(params.get("frame_end", 120))
        rotations = float(params.get("rotations", 1.0))
        axis = params.get("axis", "Z")

        obj = bridge._require_object(object_name)
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
        output_path = bridge._normalize_path(params.get("output_path"), require_exists=False)
        frame_start = int(params.get("frame_start", 1))
        frame_end = int(params.get("frame_end", 120))
        resolution_x = int(params.get("resolution_x", 512))
        resolution_y = int(params.get("resolution_y", 512))
        setup_studio = bool(params.get("setup_studio", True))

        if setup_studio:
            bridge._dispatch_command(
                "workflow_setup_studio",
                {
                    "object_name": object_name,
                    "primitive": params.get("primitive", "CUBE"),
                    "add_ground": params.get("add_ground", True),
                    "size": params.get("size", 2.0),
                },
            )

        bridge._dispatch_command(
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
        filepath = bridge._normalize_path(params.get("filepath"), require_exists=False)
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
        filepath = bridge._normalize_path(params.get("filepath"), require_exists=False)
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
    raise ValueError(f"Unsupported rendering method: {method}")
