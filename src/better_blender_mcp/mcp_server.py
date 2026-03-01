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
