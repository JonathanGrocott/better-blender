"""MCP server surface for Better Blender."""

from __future__ import annotations

from typing import Any

from better_blender_mcp.bridge_client import BlenderBridgeClient
from better_blender_mcp.config import load_config_from_env

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - dependency import at runtime
    raise RuntimeError(
        "The 'mcp' package is required. Install dependencies with 'pip install -e .[dev]'."
    ) from exc


def create_server(client: BlenderBridgeClient) -> Any:
    """Create and configure the FastMCP server instance."""

    server = FastMCP("better-blender")

    @server.tool(name="get_blender_status")
    def get_blender_status() -> dict[str, Any]:
        """Return bridge and Blender runtime status."""

        return client.call("health")

    @server.tool(name="new_scene")
    def new_scene(use_empty: bool = True) -> dict[str, Any]:
        """Create a new Blender scene from the default or empty template."""

        return client.call("new_scene", {"use_empty": use_empty})

    @server.tool(name="open_blend")
    def open_blend(filepath: str) -> dict[str, Any]:
        """Open an existing .blend file from an absolute path."""

        return client.call("open_blend", {"filepath": filepath})

    @server.tool(name="save_blend")
    def save_blend(filepath: str | None = None) -> dict[str, Any]:
        """Save the current .blend file, optionally to a new path."""

        params: dict[str, Any] = {}
        if filepath is not None:
            params["filepath"] = filepath
        return client.call("save_blend", params)

    @server.tool(name="get_scene_info")
    def get_scene_info() -> dict[str, Any]:
        """Return active scene metadata."""

        return client.call("get_scene_info")

    @server.tool(name="set_timeline")
    def set_timeline(
        frame_start: int | None = None,
        frame_end: int | None = None,
        frame_current: int | None = None,
        fps: int | None = None,
    ) -> dict[str, Any]:
        """Set timeline start/end/current frame and fps."""

        params: dict[str, Any] = {}
        if frame_start is not None:
            params["frame_start"] = frame_start
        if frame_end is not None:
            params["frame_end"] = frame_end
        if frame_current is not None:
            params["frame_current"] = frame_current
        if fps is not None:
            params["fps"] = fps
        return client.call("set_timeline", params)

    @server.tool(name="list_collections")
    def list_collections() -> dict[str, Any]:
        """List scene collections and object counts."""

        return client.call("list_collections")

    @server.tool(name="create_collection")
    def create_collection(
        name: str,
        parent_name: str | None = None,
        link_to_scene: bool = True,
    ) -> dict[str, Any]:
        """Create a new collection and link it under a parent or scene root."""

        params: dict[str, Any] = {"name": name, "link_to_scene": link_to_scene}
        if parent_name is not None:
            params["parent_name"] = parent_name
        return client.call("create_collection", params)

    @server.tool(name="add_object_to_collection")
    def add_object_to_collection(
        object_name: str,
        collection_name: str,
        unlink_from_others: bool = False,
    ) -> dict[str, Any]:
        """Link an object into a collection."""

        return client.call(
            "add_object_to_collection",
            {
                "object_name": object_name,
                "collection_name": collection_name,
                "unlink_from_others": unlink_from_others,
            },
        )

    @server.tool(name="remove_object_from_collection")
    def remove_object_from_collection(
        object_name: str,
        collection_name: str,
    ) -> dict[str, Any]:
        """Unlink an object from a collection."""

        return client.call(
            "remove_object_from_collection",
            {"object_name": object_name, "collection_name": collection_name},
        )

    @server.tool(name="list_view_layers")
    def list_view_layers() -> dict[str, Any]:
        """List scene view layers."""

        return client.call("list_view_layers")

    @server.tool(name="set_active_view_layer")
    def set_active_view_layer(name: str) -> dict[str, Any]:
        """Set the active view layer in the current window."""

        return client.call("set_active_view_layer", {"name": name})

    @server.tool(name="set_collection_visibility")
    def set_collection_visibility(
        collection_name: str,
        hide_viewport: bool | None = None,
        hide_render: bool | None = None,
        exclude: bool | None = None,
        holdout: bool | None = None,
        indirect_only: bool | None = None,
        view_layer_name: str | None = None,
    ) -> dict[str, Any]:
        """Set collection visibility globally and per-view-layer."""

        params: dict[str, Any] = {"collection_name": collection_name}
        if hide_viewport is not None:
            params["hide_viewport"] = hide_viewport
        if hide_render is not None:
            params["hide_render"] = hide_render
        if exclude is not None:
            params["exclude"] = exclude
        if holdout is not None:
            params["holdout"] = holdout
        if indirect_only is not None:
            params["indirect_only"] = indirect_only
        if view_layer_name is not None:
            params["view_layer_name"] = view_layer_name
        return client.call("set_collection_visibility", params)

    @server.tool(name="list_objects")
    def list_objects() -> dict[str, Any]:
        """List objects in the active scene."""

        return client.call("list_objects")

    @server.tool(name="get_object_info")
    def get_object_info(name: str) -> dict[str, Any]:
        """Get details for a specific object by name."""

        return client.call("get_object_info", {"name": name})

    @server.tool(name="create_primitive")
    def create_primitive(
        primitive: str = "CUBE",
        name: str | None = None,
        size: float = 2.0,
        location: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create a mesh primitive."""

        params: dict[str, Any] = {
            "primitive": primitive,
            "size": size,
            "location": location or [0.0, 0.0, 0.0],
            "rotation": rotation or [0.0, 0.0, 0.0],
            "scale": scale or [1.0, 1.0, 1.0],
        }
        if name is not None:
            params["name"] = name
        return client.call("create_primitive", params)

    @server.tool(name="delete_object")
    def delete_object(name: str) -> dict[str, Any]:
        """Delete an object by name."""

        return client.call("delete_object", {"name": name})

    @server.tool(name="set_object_transform")
    def set_object_transform(
        name: str,
        location: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> dict[str, Any]:
        """Set transform values for an object."""

        params: dict[str, Any] = {"name": name}
        if location is not None:
            params["location"] = location
        if rotation is not None:
            params["rotation"] = rotation
        if scale is not None:
            params["scale"] = scale

        return client.call("set_object_transform", params)

    @server.tool(name="duplicate_object")
    def duplicate_object(
        name: str,
        new_name: str | None = None,
        linked: bool = False,
    ) -> dict[str, Any]:
        """Duplicate an object."""

        params: dict[str, Any] = {"name": name, "linked": linked}
        if new_name is not None:
            params["new_name"] = new_name
        return client.call("duplicate_object", params)

    @server.tool(name="keyframe_transform")
    def keyframe_transform(
        name: str,
        frame: int,
        location: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> dict[str, Any]:
        """Set object transform values and insert keyframes at a frame."""

        params: dict[str, Any] = {"name": name, "frame": frame}
        if location is not None:
            params["location"] = location
        if rotation is not None:
            params["rotation"] = rotation
        if scale is not None:
            params["scale"] = scale
        return client.call("keyframe_transform", params)

    @server.tool(name="insert_keyframe")
    def insert_keyframe(
        name: str,
        data_path: str,
        frame: int,
        index: int = -1,
    ) -> dict[str, Any]:
        """Insert a keyframe for an arbitrary object data path."""

        return client.call(
            "insert_keyframe",
            {
                "name": name,
                "data_path": data_path,
                "frame": frame,
                "index": index,
            },
        )

    @server.tool(name="list_animation_data")
    def list_animation_data(name: str) -> dict[str, Any]:
        """List animation curves for an object."""

        return client.call("list_animation_data", {"name": name})

    @server.tool(name="list_actions")
    def list_actions() -> dict[str, Any]:
        """List actions in the .blend file."""

        return client.call("list_actions")

    @server.tool(name="create_action")
    def create_action(
        name: str,
        object_name: str | None = None,
        set_active: bool = True,
    ) -> dict[str, Any]:
        """Create an action and optionally assign it to an object."""

        params: dict[str, Any] = {"name": name, "set_active": set_active}
        if object_name is not None:
            params["object_name"] = object_name
        return client.call("create_action", params)

    @server.tool(name="set_active_action")
    def set_active_action(object_name: str, action_name: str) -> dict[str, Any]:
        """Set an object's active action."""

        return client.call(
            "set_active_action",
            {"object_name": object_name, "action_name": action_name},
        )

    @server.tool(name="push_down_action")
    def push_down_action(object_name: str) -> dict[str, Any]:
        """Push active action to NLA track and clear active action."""

        return client.call("push_down_action", {"object_name": object_name})

    @server.tool(name="clear_animation_data")
    def clear_animation_data(object_name: str) -> dict[str, Any]:
        """Clear all animation data from an object."""

        return client.call("clear_animation_data", {"object_name": object_name})

    @server.tool(name="duplicate_action")
    def duplicate_action(action_name: str, new_name: str | None = None) -> dict[str, Any]:
        """Duplicate an action and optionally provide the new action name."""

        params: dict[str, Any] = {"action_name": action_name}
        if new_name is not None:
            params["new_name"] = new_name
        return client.call("duplicate_action", params)

    @server.tool(name="delete_action")
    def delete_action(action_name: str, force: bool = False) -> dict[str, Any]:
        """Delete an action. Set force=true to remove even when it has users."""

        return client.call("delete_action", {"action_name": action_name, "force": force})

    @server.tool(name="list_nla_tracks")
    def list_nla_tracks(object_name: str) -> dict[str, Any]:
        """List NLA tracks and strips for an object."""

        return client.call("list_nla_tracks", {"object_name": object_name})

    @server.tool(name="create_nla_strip")
    def create_nla_strip(
        object_name: str,
        action_name: str,
        track_name: str | None = None,
        strip_name: str | None = None,
        frame_start: float | None = None,
    ) -> dict[str, Any]:
        """Create an NLA strip for an action on an object's track."""

        params: dict[str, Any] = {"object_name": object_name, "action_name": action_name}
        if track_name is not None:
            params["track_name"] = track_name
        if strip_name is not None:
            params["strip_name"] = strip_name
        if frame_start is not None:
            params["frame_start"] = frame_start
        return client.call("create_nla_strip", params)

    @server.tool(name="set_nla_strip")
    def set_nla_strip(
        object_name: str,
        track_name: str,
        strip_name: str,
        frame_start: float | None = None,
        frame_end: float | None = None,
        action_frame_start: float | None = None,
        action_frame_end: float | None = None,
        scale: float | None = None,
        repeat: float | None = None,
        mute: bool | None = None,
    ) -> dict[str, Any]:
        """Update timing and playback settings for an NLA strip."""

        params: dict[str, Any] = {
            "object_name": object_name,
            "track_name": track_name,
            "strip_name": strip_name,
        }
        if frame_start is not None:
            params["frame_start"] = frame_start
        if frame_end is not None:
            params["frame_end"] = frame_end
        if action_frame_start is not None:
            params["action_frame_start"] = action_frame_start
        if action_frame_end is not None:
            params["action_frame_end"] = action_frame_end
        if scale is not None:
            params["scale"] = scale
        if repeat is not None:
            params["repeat"] = repeat
        if mute is not None:
            params["mute"] = mute
        return client.call("set_nla_strip", params)

    @server.tool(name="remove_nla_strip")
    def remove_nla_strip(object_name: str, track_name: str, strip_name: str) -> dict[str, Any]:
        """Remove an NLA strip from a track."""

        return client.call(
            "remove_nla_strip",
            {
                "object_name": object_name,
                "track_name": track_name,
                "strip_name": strip_name,
            },
        )

    @server.tool(name="create_geometry_nodes_modifier")
    def create_geometry_nodes_modifier(
        object_name: str,
        modifier_name: str = "GeometryNodes",
    ) -> dict[str, Any]:
        """Create or return a geometry nodes modifier and node tree."""

        return client.call(
            "create_geometry_nodes_modifier",
            {"object_name": object_name, "modifier_name": modifier_name},
        )

    @server.tool(name="list_geometry_nodes")
    def list_geometry_nodes(
        object_name: str,
        modifier_name: str = "GeometryNodes",
    ) -> dict[str, Any]:
        """List geometry nodes and links for a modifier."""

        return client.call(
            "list_geometry_nodes",
            {"object_name": object_name, "modifier_name": modifier_name},
        )

    @server.tool(name="add_geometry_node")
    def add_geometry_node(
        object_name: str,
        node_type: str,
        modifier_name: str = "GeometryNodes",
        node_name: str | None = None,
    ) -> dict[str, Any]:
        """Add a node to a geometry node tree."""

        params: dict[str, Any] = {
            "object_name": object_name,
            "modifier_name": modifier_name,
            "node_type": node_type,
        }
        if node_name is not None:
            params["node_name"] = node_name
        return client.call("add_geometry_node", params)

    @server.tool(name="link_geometry_nodes")
    def link_geometry_nodes(
        object_name: str,
        from_node: str,
        from_socket: str,
        to_node: str,
        to_socket: str,
        modifier_name: str = "GeometryNodes",
    ) -> dict[str, Any]:
        """Create a link between geometry nodes sockets."""

        return client.call(
            "link_geometry_nodes",
            {
                "object_name": object_name,
                "modifier_name": modifier_name,
                "from_node": from_node,
                "from_socket": from_socket,
                "to_node": to_node,
                "to_socket": to_socket,
            },
        )

    @server.tool(name="add_geometry_input")
    def add_geometry_input(
        object_name: str,
        input_name: str,
        socket_type: str = "NodeSocketFloat",
        default_value: Any | None = None,
        modifier_name: str = "GeometryNodes",
    ) -> dict[str, Any]:
        """Add an input socket to a geometry-node group interface."""

        return client.call(
            "add_geometry_input",
            {
                "object_name": object_name,
                "modifier_name": modifier_name,
                "input_name": input_name,
                "socket_type": socket_type,
                "default_value": default_value,
            },
        )

    @server.tool(name="list_geometry_inputs")
    def list_geometry_inputs(
        object_name: str,
        modifier_name: str = "GeometryNodes",
    ) -> dict[str, Any]:
        """List editable geometry-node group inputs for a modifier."""

        return client.call(
            "list_geometry_inputs",
            {"object_name": object_name, "modifier_name": modifier_name},
        )

    @server.tool(name="set_geometry_input")
    def set_geometry_input(
        object_name: str,
        input_name_or_identifier: str,
        value: Any | None = None,
        modifier_name: str = "GeometryNodes",
        use_attribute: bool | None = None,
        attribute_name: str | None = None,
    ) -> dict[str, Any]:
        """Set a geometry-node input value or attribute binding."""

        params: dict[str, Any] = {
            "object_name": object_name,
            "modifier_name": modifier_name,
            "input_name_or_identifier": input_name_or_identifier,
            "value": value,
        }
        if use_attribute is not None:
            params["use_attribute"] = use_attribute
        if attribute_name is not None:
            params["attribute_name"] = attribute_name
        return client.call("set_geometry_input", params)

    @server.tool(name="add_modifier")
    def add_modifier(
        object_name: str,
        modifier_type: str,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a modifier to an object and apply optional settings."""

        params: dict[str, Any] = {
            "object_name": object_name,
            "modifier_type": modifier_type,
        }
        if name is not None:
            params["name"] = name
        if settings is not None:
            params["settings"] = settings
        return client.call("add_modifier", params)

    @server.tool(name="list_modifiers")
    def list_modifiers(object_name: str) -> dict[str, Any]:
        """List modifiers on an object."""

        return client.call("list_modifiers", {"object_name": object_name})

    @server.tool(name="apply_modifier")
    def apply_modifier(object_name: str, modifier_name: str) -> dict[str, Any]:
        """Apply a modifier on an object."""

        return client.call(
            "apply_modifier",
            {"object_name": object_name, "modifier_name": modifier_name},
        )

    @server.tool(name="remove_modifier")
    def remove_modifier(object_name: str, modifier_name: str) -> dict[str, Any]:
        """Remove a modifier from an object."""

        return client.call(
            "remove_modifier",
            {"object_name": object_name, "modifier_name": modifier_name},
        )

    @server.tool(name="add_constraint")
    def add_constraint(
        object_name: str,
        constraint_type: str,
        name: str | None = None,
        target_name: str | None = None,
    ) -> dict[str, Any]:
        """Add a constraint to an object and optionally assign target."""

        params: dict[str, Any] = {
            "object_name": object_name,
            "constraint_type": constraint_type,
        }
        if name is not None:
            params["name"] = name
        if target_name is not None:
            params["target_name"] = target_name
        return client.call("add_constraint", params)

    @server.tool(name="list_constraints")
    def list_constraints(object_name: str) -> dict[str, Any]:
        """List constraints on an object."""

        return client.call("list_constraints", {"object_name": object_name})

    @server.tool(name="remove_constraint")
    def remove_constraint(object_name: str, constraint_name: str) -> dict[str, Any]:
        """Remove a constraint from an object."""

        return client.call(
            "remove_constraint",
            {"object_name": object_name, "constraint_name": constraint_name},
        )

    @server.tool(name="create_material")
    def create_material(
        name: str,
        base_color: list[float] | None = None,
        roughness: float = 0.5,
        metallic: float = 0.0,
    ) -> dict[str, Any]:
        """Create or update a material with principled parameters."""

        return client.call(
            "create_material",
            {
                "name": name,
                "base_color": base_color or [0.8, 0.8, 0.8, 1.0],
                "roughness": roughness,
                "metallic": metallic,
            },
        )

    @server.tool(name="assign_material")
    def assign_material(
        object_name: str,
        material_name: str,
        slot_index: int | None = None,
    ) -> dict[str, Any]:
        """Assign a material to an object slot or append to material list."""

        params: dict[str, Any] = {
            "object_name": object_name,
            "material_name": material_name,
        }
        if slot_index is not None:
            params["slot_index"] = slot_index
        return client.call("assign_material", params)

    @server.tool(name="create_camera")
    def create_camera(
        name: str = "Camera",
        location: list[float] | None = None,
        rotation: list[float] | None = None,
        set_active: bool = True,
    ) -> dict[str, Any]:
        """Create a camera object and optionally set it active."""

        return client.call(
            "create_camera",
            {
                "name": name,
                "location": location or [0.0, -6.0, 3.0],
                "rotation": rotation or [1.1, 0.0, 0.0],
                "set_active": set_active,
            },
        )

    @server.tool(name="set_active_camera")
    def set_active_camera(name: str) -> dict[str, Any]:
        """Set the active scene camera by object name."""

        return client.call("set_active_camera", {"name": name})

    @server.tool(name="create_light")
    def create_light(
        name: str = "Light",
        light_type: str = "POINT",
        energy: float = 1000.0,
        location: list[float] | None = None,
        rotation: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create a light object."""

        return client.call(
            "create_light",
            {
                "name": name,
                "light_type": light_type,
                "energy": energy,
                "location": location or [4.0, -4.0, 6.0],
                "rotation": rotation or [0.6, 0.0, 0.8],
            },
        )

    @server.tool(name="enable_compositor")
    def enable_compositor(use_nodes: bool = True, clear_nodes: bool = False) -> dict[str, Any]:
        """Enable compositor nodes and optionally reset node tree."""

        return client.call(
            "enable_compositor",
            {"use_nodes": use_nodes, "clear_nodes": clear_nodes},
        )

    @server.tool(name="list_compositor_nodes")
    def list_compositor_nodes() -> dict[str, Any]:
        """List compositor nodes and links."""

        return client.call("list_compositor_nodes")

    @server.tool(name="add_compositor_node")
    def add_compositor_node(node_type: str, node_name: str | None = None) -> dict[str, Any]:
        """Add a compositor node by Blender node type id."""

        params: dict[str, Any] = {"node_type": node_type}
        if node_name is not None:
            params["node_name"] = node_name
        return client.call("add_compositor_node", params)

    @server.tool(name="link_compositor_nodes")
    def link_compositor_nodes(
        from_node: str,
        from_socket: str,
        to_node: str,
        to_socket: str,
    ) -> dict[str, Any]:
        """Link sockets between two compositor nodes."""

        return client.call(
            "link_compositor_nodes",
            {
                "from_node": from_node,
                "from_socket": from_socket,
                "to_node": to_node,
                "to_socket": to_socket,
            },
        )

    @server.tool(name="set_view_layer_passes")
    def set_view_layer_passes(
        view_layer_name: str | None = None,
        use_pass_z: bool | None = None,
        use_pass_normal: bool | None = None,
        use_pass_vector: bool | None = None,
        use_pass_diffuse_color: bool | None = None,
        use_pass_glossy_color: bool | None = None,
        use_pass_emit: bool | None = None,
        use_pass_ambient_occlusion: bool | None = None,
    ) -> dict[str, Any]:
        """Configure common render passes on a view layer."""

        params: dict[str, Any] = {}
        if view_layer_name is not None:
            params["view_layer_name"] = view_layer_name
        if use_pass_z is not None:
            params["use_pass_z"] = use_pass_z
        if use_pass_normal is not None:
            params["use_pass_normal"] = use_pass_normal
        if use_pass_vector is not None:
            params["use_pass_vector"] = use_pass_vector
        if use_pass_diffuse_color is not None:
            params["use_pass_diffuse_color"] = use_pass_diffuse_color
        if use_pass_glossy_color is not None:
            params["use_pass_glossy_color"] = use_pass_glossy_color
        if use_pass_emit is not None:
            params["use_pass_emit"] = use_pass_emit
        if use_pass_ambient_occlusion is not None:
            params["use_pass_ambient_occlusion"] = use_pass_ambient_occlusion
        return client.call("set_view_layer_passes", params)

    @server.tool(name="workflow_setup_studio")
    def workflow_setup_studio(
        object_name: str = "Subject",
        primitive: str = "CUBE",
        size: float = 2.0,
        add_ground: bool = True,
        camera_name: str = "WorkflowCamera",
        camera_distance: float = 6.0,
        camera_height: float = 3.0,
        key_energy: float = 1200.0,
        fill_energy: float = 600.0,
        rim_energy: float = 900.0,
    ) -> dict[str, Any]:
        """Set up a studio-style scene with subject, camera, and three-point lighting."""

        return client.call(
            "workflow_setup_studio",
            {
                "object_name": object_name,
                "primitive": primitive,
                "size": size,
                "add_ground": add_ground,
                "camera_name": camera_name,
                "camera_distance": camera_distance,
                "camera_height": camera_height,
                "key_energy": key_energy,
                "fill_energy": fill_energy,
                "rim_energy": rim_energy,
            },
        )

    @server.tool(name="workflow_create_turntable")
    def workflow_create_turntable(
        object_name: str,
        frame_start: int = 1,
        frame_end: int = 120,
        rotations: float = 1.0,
        axis: str = "Z",
    ) -> dict[str, Any]:
        """Create turntable keyframes on an object."""

        return client.call(
            "workflow_create_turntable",
            {
                "object_name": object_name,
                "frame_start": frame_start,
                "frame_end": frame_end,
                "rotations": rotations,
                "axis": axis,
            },
        )

    @server.tool(name="workflow_turntable_render")
    def workflow_turntable_render(
        output_path: str,
        object_name: str = "Subject",
        frame_start: int = 1,
        frame_end: int = 120,
        rotations: float = 1.0,
        axis: str = "Z",
        setup_studio: bool = True,
        primitive: str = "CUBE",
        size: float = 2.0,
        add_ground: bool = True,
        engine: str | None = None,
        resolution_x: int = 512,
        resolution_y: int = 512,
        samples: int | None = None,
    ) -> dict[str, Any]:
        """One-call turntable workflow: setup, animate, and render."""

        params: dict[str, Any] = {
            "output_path": output_path,
            "object_name": object_name,
            "frame_start": frame_start,
            "frame_end": frame_end,
            "rotations": rotations,
            "axis": axis,
            "setup_studio": setup_studio,
            "primitive": primitive,
            "size": size,
            "add_ground": add_ground,
            "resolution_x": resolution_x,
            "resolution_y": resolution_y,
        }
        if engine is not None:
            params["engine"] = engine
        if samples is not None:
            params["samples"] = samples
        return client.call("workflow_turntable_render", params)

    @server.tool(name="render_still")
    def render_still(
        filepath: str,
        engine: str | None = None,
        resolution_x: int | None = None,
        resolution_y: int | None = None,
        samples: int | None = None,
    ) -> dict[str, Any]:
        """Render a still frame to disk."""

        params: dict[str, Any] = {"filepath": filepath}
        if engine is not None:
            params["engine"] = engine
        if resolution_x is not None:
            params["resolution_x"] = resolution_x
        if resolution_y is not None:
            params["resolution_y"] = resolution_y
        if samples is not None:
            params["samples"] = samples

        return client.call("render_still", params)

    @server.tool(name="render_animation")
    def render_animation(
        filepath: str,
        engine: str | None = None,
        frame_start: int | None = None,
        frame_end: int | None = None,
    ) -> dict[str, Any]:
        """Render animation frames to disk sequence."""

        params: dict[str, Any] = {"filepath": filepath}
        if engine is not None:
            params["engine"] = engine
        if frame_start is not None:
            params["frame_start"] = frame_start
        if frame_end is not None:
            params["frame_end"] = frame_end
        return client.call("render_animation", params)

    @server.tool(name="import_file")
    def import_file(filepath: str, file_type: str | None = None) -> dict[str, Any]:
        """Import a supported 3D file."""

        params: dict[str, Any] = {"filepath": filepath}
        if file_type is not None:
            params["file_type"] = file_type

        return client.call("import_file", params)

    @server.tool(name="export_file")
    def export_file(
        filepath: str,
        file_type: str | None = None,
        use_selection: bool = False,
    ) -> dict[str, Any]:
        """Export scene data to a supported file format."""

        params: dict[str, Any] = {"filepath": filepath, "use_selection": use_selection}
        if file_type is not None:
            params["file_type"] = file_type

        return client.call("export_file", params)

    @server.tool(name="execute_blender_code")
    def execute_blender_code(code: str) -> dict[str, Any]:
        """Execute Python code in Blender when unsafe mode is enabled."""

        return client.call("execute_code", {"code": code})

    return server


def run_server() -> None:
    """Run the MCP server using stdio transport."""

    config = load_config_from_env()
    client = BlenderBridgeClient(config.bridge)
    server = create_server(client)
    server.run()
