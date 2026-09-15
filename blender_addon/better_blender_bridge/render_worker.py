"""Run a captured scene render in a cancellable, isolated Blender process."""

import json
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import bpy

    from better_blender_bridge import _dispatch_command
    from better_blender_bridge.storage import write_json

    request_path, result_path = sys.argv[sys.argv.index("--") + 1 :]
    request = json.loads(Path(request_path).read_text())
    bpy.context.window.scene = bpy.data.scenes[request["scene_name"]]
    outputs = []
    frames_written = 0

    def frame_written(scene, *_args):
        nonlocal frames_written
        frames_written += 1
        if request["method"] == "render_still":
            output = bpy.path.ensure_ext(scene.render.filepath, scene.render.file_extension)
            total = 1
        else:
            output = scene.render.frame_path(frame=scene.frame_current)
            total = (scene.frame_end - scene.frame_start) // scene.frame_step + 1
        if len(outputs) < 1000:
            outputs.append(str(Path(output).resolve()))
        write_json(
            Path(result_path).with_name("progress.json"),
            {
                "frames_completed": frames_written,
                "frames_total": total,
                "frame_current": scene.frame_current,
                "fraction": min(1, frames_written / total),
            },
        )

    bpy.app.handlers.render_write.append(frame_written)
    try:
        result = _dispatch_command(request["method"], request["params"])
    finally:
        bpy.app.handlers.render_write.remove(frame_written)
    result.update(
        outputs=outputs,
        frames_written=frames_written,
        outputs_truncated=frames_written > len(outputs),
    )
    Path(result_path).write_text(json.dumps(result))


if __name__ == "__main__":
    main()
