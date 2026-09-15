"""Drive real Blender timers and UI operators from a disposable GUI process."""

import json
import queue
import socket
import sys
import threading
import traceback
from pathlib import Path

import bpy

addon_parent, directory = sys.argv[sys.argv.index("--") + 1 :]
sys.path.insert(0, addon_parent)
directory = Path(directory)
commands = queue.Queue()
result = {}
finished = threading.Event()
with socket.socket() as reservation:
    reservation.bind(("127.0.0.1", 0))
    port = reservation.getsockname()[1]


def enable():
    bpy.ops.preferences.addon_enable(module="better_blender_bridge")
    import better_blender_bridge as bridge

    prefs = bpy.context.preferences.addons["better_blender_bridge"].preferences
    prefs.port = port
    prefs.token = "gui-test"
    bpy.ops.better_blender.start_bridge()
    assert bridge._RUNTIME.running
    assert bpy.app.timers.is_registered(bridge._drain_command_queue)


def call(method, params=None):
    with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:
        sock.sendall(
            (
                json.dumps(
                    {"id": method, "method": method, "params": params or {}, "token": "gui-test"}
                )
                + "\n"
            ).encode()
        )
        response = json.loads(sock.makefile("rb").readline())
        assert response["ok"], response
        return response["result"]


def control(action):
    done = threading.Event()
    commands.put((action, done))
    assert done.wait(15), action
    assert not result.get("error"), result


def exercise():
    try:
        call("health")
        saved = directory / "lifecycle.blend"
        call("save_blend", {"filepath": str(saved)})
        capture = call(
            "capture_viewport_screenshot",
            {
                "filepath": str(directory / "viewport.png"),
                "fallback_to_render": False,
                "view": "FRONT",
                "resolution_x": 256,
                "resolution_y": 256,
            },
        )
        assert capture["capture_mode"] == "viewport_opengl", capture
        call("new_scene", {"use_empty": True})
        assert call("get_scene_info")["objects_total"] == 0
        call("open_blend", {"filepath": str(saved)})
        assert call("get_scene_info")["objects_total"] == 3
        control("restart")
        call("health")
        control("disable_enable")
        call("health")
        control("verify_image")
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        finished.set()


def driver():
    try:
        while not commands.empty():
            action, done = commands.get_nowait()
            try:
                import better_blender_bridge as bridge

                if action == "restart":
                    bpy.ops.better_blender.stop_bridge()
                    assert not bpy.app.timers.is_registered(bridge._drain_command_queue)
                    bpy.ops.better_blender.start_bridge()
                elif action == "disable_enable":
                    bpy.ops.preferences.addon_disable(module="better_blender_bridge")
                    assert bridge._RUNTIME is None
                    assert not bpy.app.timers.is_registered(bridge._drain_command_queue)
                    enable()
                else:
                    image = bpy.data.images.load(str(directory / "viewport.png"))
                    assert tuple(image.size) == (256, 256)
                    pixels = list(image.pixels)
                    assert max(pixels[0::4]) - min(pixels[0::4]) > 0.05
                    bpy.data.images.remove(image)
            finally:
                done.set()
        if finished.is_set():
            (directory / "result.json").write_text(json.dumps(result))
            bpy.ops.wm.quit_blender()
            return None
    except Exception:
        result["error"] = traceback.format_exc()
        finished.set()
    return 0.05


def begin():
    try:
        enable()
        bpy.app.timers.register(driver, persistent=True)
        threading.Thread(target=exercise, daemon=True).start()
    except Exception:
        (directory / "result.json").write_text(json.dumps({"error": traceback.format_exc()}))
        bpy.ops.wm.quit_blender()
    return None


# Let Blender initialize its window and viewport before starting the scenario.
bpy.app.timers.register(begin, first_interval=1.0)
