"""Regenerate the dependency-free Blender input schemas after changing MCP tools."""

import asyncio
import json
from pathlib import Path

from better_blender_mcp.bridge_client import BlenderBridgeClient
from better_blender_mcp.config import BridgeConfig
from better_blender_mcp.mcp_server import create_server


async def main():
    tools = await create_server(BlenderBridgeClient(BridgeConfig())).list_tools()
    aliases = {"get_blender_status": "health", "execute_blender_code": "execute_code"}
    schemas = {}
    for tool in tools:
        schema = tool.inputSchema
        schema["additionalProperties"] = False
        schemas[aliases.get(tool.name, tool.name)] = schema
    schemas["start_render_job"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["method", "params"],
        "properties": {
            "method": {
                "type": "string",
                "enum": [
                    "render_still",
                    "render_animation",
                    "workflow_turntable_render",
                ],
            },
            "params": {"type": "object"},
        },
    }
    target = (
        Path(__file__).resolve().parents[1] / "blender_addon/better_blender_bridge/schemas.json"
    )
    target.write_text(json.dumps(schemas, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
