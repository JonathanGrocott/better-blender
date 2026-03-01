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
        return client.call("health")

    @server.tool(name="get_scene_info")
    def get_scene_info() -> dict[str, Any]:
        return client.call("get_scene_info")

    @server.tool(name="list_objects")
    def list_objects() -> dict[str, Any]:
        return client.call("list_objects")

    return server


def run_server() -> None:
    """Run the MCP server using stdio transport."""

    config = load_config_from_env()
    client = BlenderBridgeClient(config.bridge)
    server = create_server(client)
    server.run()
