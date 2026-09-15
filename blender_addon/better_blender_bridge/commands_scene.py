"""Main-thread scene commands. Shared validation and helpers come from the bridge context."""

from __future__ import annotations

from pathlib import Path

import bpy

METHODS = frozenset(
    [
        "new_scene",
        "open_blend",
        "save_blend",
        "get_scene_info",
        "set_timeline",
        "import_file",
        "export_file",
    ]
)


def dispatch(method, params, bridge):
    if method == "new_scene":
        use_empty = bool(params.get("use_empty", True))
        bpy.ops.wm.read_homefile(use_empty=use_empty)
        return bridge._dispatch_command("get_scene_info", {})

    if method == "open_blend":
        filepath = bridge._normalize_path(params.get("filepath"), require_exists=True)
        bpy.ops.wm.open_mainfile(filepath=filepath, use_scripts=False)
        return bridge._dispatch_command("get_scene_info", {})

    if method == "save_blend":
        filepath = params.get("filepath")
        if filepath is None:
            if not bpy.data.filepath:
                raise ValueError("Current blend file has no path. Provide filepath.")
            bridge._normalize_path(bpy.data.filepath, require_exists=False)
            bpy.ops.wm.save_mainfile()
        else:
            normalized = bridge._normalize_path(filepath, require_exists=False)
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

    if method == "import_file":
        filepath = bridge._normalize_path(params.get("filepath"), require_exists=True)
        file_type = bridge._resolve_file_type(filepath, params.get("file_type"))

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
        filepath = bridge._normalize_path(params.get("filepath"), require_exists=False)
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        file_type = bridge._resolve_file_type(filepath, params.get("file_type"))
        use_selection = bool(params.get("use_selection", False))

        if file_type == "OBJ":
            bpy.ops.wm.obj_export(filepath=filepath, export_selected_objects=use_selection)
        elif file_type == "FBX":
            bpy.ops.export_scene.fbx(filepath=filepath, use_selection=use_selection)
        elif file_type == "GLTF":
            operator = bpy.ops.export_scene.gltf
            selection_key = (
                "use_selection"
                if "use_selection" in operator.get_rna_type().properties
                else "export_selected"
            )
            operator(
                filepath=filepath,
                **{selection_key: use_selection},
                export_format="GLB" if Path(filepath).suffix.lower() == ".glb" else "GLTF_SEPARATE",
            )
        else:
            bpy.ops.wm.usd_export(filepath=filepath, selected_objects_only=use_selection)

        return {"exported": True, "file_type": file_type, "filepath": filepath}
    raise ValueError(f"Unsupported scene method: {method}")
