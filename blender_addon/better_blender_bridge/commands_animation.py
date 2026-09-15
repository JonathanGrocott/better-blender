"""Main-thread animation commands. Shared validation and helpers come from the bridge context."""

from __future__ import annotations

import bpy

METHODS = frozenset(
    [
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
    ]
)


def dispatch(method, params, bridge):
    if method == "keyframe_transform":
        obj = bridge._require_object(params.get("name"))
        frame = params.get("frame")
        if not isinstance(frame, int):
            raise ValueError("frame must be an integer")

        location_set = "location" in params
        rotation_set = "rotation" in params
        scale_set = "scale" in params
        if not location_set and not rotation_set and not scale_set:
            raise ValueError("At least one of location, rotation, or scale must be provided")

        if location_set:
            obj.location = bridge._to_vector3(params["location"], "location")
            obj.keyframe_insert(data_path="location", frame=frame)
        if rotation_set:
            obj.rotation_euler = bridge._to_vector3(params["rotation"], "rotation")
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)
        if scale_set:
            obj.scale = bridge._to_vector3(params["scale"], "scale")
            obj.keyframe_insert(data_path="scale", frame=frame)

        return {"object": bridge._serialize_object(obj), "frame": frame}

    if method == "insert_keyframe":
        obj = bridge._require_object(params.get("name"))
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
        obj = bridge._require_object(params.get("name"))
        animation_data = obj.animation_data
        if animation_data is None or animation_data.action is None:
            return {"name": obj.name, "has_animation": False, "action": None, "fcurves": []}

        action = animation_data.action
        curves = bridge._iter_action_fcurves(action)
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
            obj = bridge._require_object(object_name)
            if obj.animation_data is None:
                obj.animation_data_create()
            if set_active:
                obj.animation_data.action = action

        return {"action": {"name": action.name, "users": action.users}}

    if method == "set_active_action":
        object_name = params.get("object_name")
        action_name = params.get("action_name")

        obj = bridge._require_object(object_name)
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
        obj = bridge._require_object(object_name)

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
        obj = bridge._require_object(object_name)
        obj.animation_data_clear()
        return {"object_name": obj.name, "cleared": True}

    if method == "duplicate_action":
        action_name = params.get("action_name")
        new_name = params.get("new_name")
        action = bridge._require_action(action_name)

        if not isinstance(new_name, str) or not new_name:
            new_name = f"{action.name}_copy"

        copy = action.copy()
        copy.name = new_name
        return {"action": {"name": copy.name, "users": copy.users}}

    if method == "delete_action":
        action_name = params.get("action_name")
        force = bool(params.get("force", False))
        action = bridge._require_action(action_name)

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
        obj = bridge._require_object(object_name)
        if obj.animation_data is None:
            return {"object_name": obj.name, "tracks": [], "count": 0}

        tracks = []
        for track in obj.animation_data.nla_tracks:
            strips = [bridge._serialize_nla_strip(strip) for strip in track.strips]
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

        obj = bridge._require_object(object_name)
        action = bridge._require_action(action_name)
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
        strip.name = new_strip_name

        return {
            "object_name": obj.name,
            "track_name": track.name,
            "strip": bridge._serialize_nla_strip(strip),
        }

    if method == "set_nla_strip":
        object_name = params.get("object_name")
        track_name = params.get("track_name")
        strip_name = params.get("strip_name")

        obj = bridge._require_object(object_name)
        track = bridge._require_nla_track(obj, track_name)
        strip = bridge._require_nla_strip(track, strip_name)

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
            "strip": bridge._serialize_nla_strip(strip),
        }

    if method == "remove_nla_strip":
        object_name = params.get("object_name")
        track_name = params.get("track_name")
        strip_name = params.get("strip_name")

        obj = bridge._require_object(object_name)
        track = bridge._require_nla_track(obj, track_name)
        strip = bridge._require_nla_strip(track, strip_name)
        track.strips.remove(strip)
        return {"object_name": obj.name, "track_name": track.name, "removed_strip": strip_name}

    raise ValueError(f"Unsupported animation method: {method}")
