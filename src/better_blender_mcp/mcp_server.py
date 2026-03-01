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

    @server.tool(name="list_collections")
    def list_collections() -> dict[str, Any]:
        """List scene collections and object counts."""

        return client.call("list_collections")

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
