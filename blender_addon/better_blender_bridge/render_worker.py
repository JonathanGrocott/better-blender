"""Run a captured scene render in a cancellable, isolated Blender process."""

import json
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import bpy

    from better_blender_bridge import _dispatch_command

    request_path, result_path = sys.argv[sys.argv.index("--") + 1 :]
    request = json.loads(Path(request_path).read_text())
    bpy.context.window.scene = bpy.data.scenes[request["scene_name"]]
    result = _dispatch_command(request["method"], request["params"])
    Path(result_path).write_text(json.dumps(result))


if __name__ == "__main__":
    main()
