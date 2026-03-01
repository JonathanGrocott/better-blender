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
from typing import Any

import bpy

bl_info = {
    "name": "Better Blender Bridge",
    "author": "Better Blender Contributors",
    "version": (0, 1, 0),
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


def _dispatch_command(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "health":
        return {
            "bridge_running": True,
            "blender_version": bpy.app.version_string,
            "file_path": bpy.data.filepath,
            "timestamp": time.time(),
        }

    if method == "get_scene_info":
        scene = bpy.context.scene
        return {
            "scene_name": scene.name,
            "frame_current": scene.frame_current,
            "objects_total": len(scene.objects),
            "file_path": bpy.data.filepath,
        }

    if method == "list_objects":
        scene = bpy.context.scene
        objects = [{"name": obj.name, "type": obj.type} for obj in scene.objects]
        return {"objects": objects, "count": len(objects)}

    raise ValueError(f"Unsupported method: {method}")


def _drain_command_queue() -> float | None:
    global _RUNTIME

    if _RUNTIME is None or not _RUNTIME.running or _RUNTIME.command_queue is None:
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

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.prop(self, "token")
        layout.prop(self, "timeout_seconds")


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
