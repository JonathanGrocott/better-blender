import asyncio
import threading

from better_blender_mcp.bridge_client import BlenderBridgeClient
from better_blender_mcp.config import BridgeConfig
from better_blender_mcp.mcp_server import create_server


def test_bridge_wait_does_not_block_mcp_event_loop():
    started = threading.Event()
    release = threading.Event()

    class SlowClient(BlenderBridgeClient):
        def call(self, method, params=None):
            started.set()
            assert release.wait(timeout=2), "MCP event loop could not release socket worker"
            return {"bridge_running": True}

    async def check():
        server = create_server(SlowClient(BridgeConfig()))
        task = asyncio.create_task(server.call_tool("get_blender_status", {}))
        try:
            async with asyncio.timeout(1):
                while not started.is_set():
                    await asyncio.sleep(0.01)
            # Discovery must remain responsive while a tool is waiting for Blender.
            tools = await asyncio.wait_for(server.list_tools(), timeout=0.5)
            assert any(tool.name == "get_blender_status" for tool in tools)
            assert not task.done()
        finally:
            release.set()
        await task

    asyncio.run(check())


def test_generated_bridge_schemas_match_mcp_tools():
    import json
    from pathlib import Path

    aliases = {"get_blender_status": "health", "execute_blender_code": "execute_code"}
    schemas = json.loads(
        (
            Path(__file__).resolve().parents[1] / "blender_addon/better_blender_bridge/schemas.json"
        ).read_text()
    )
    tools = asyncio.run(create_server(BlenderBridgeClient(BridgeConfig())).list_tools())
    for tool in tools:
        expected = {**tool.inputSchema, "additionalProperties": False}
        assert schemas[aliases.get(tool.name, tool.name)] == expected
