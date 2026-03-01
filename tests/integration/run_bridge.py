"""Run the Better Blender bridge inside headless Blender for integration testing."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon-parent", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--stop-file", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--allow-unsafe-code", action="store_true")

    if "--" not in sys.argv:
        raise RuntimeError("Expected '--' separator with bridge runner arguments")

    index = sys.argv.index("--")
    return parser.parse_args(sys.argv[index + 1 :])


def main() -> None:
    args = _parse_args()

    addon_parent = Path(args.addon_parent).resolve()
    sys.path.insert(0, str(addon_parent))

    import better_blender_bridge as bridge  # noqa: PLC0415

    bridge.start_bridge_with_config(
        host=args.host,
        port=args.port,
        token=args.token,
        timeout_seconds=args.timeout_seconds,
        allow_unsafe_code=args.allow_unsafe_code,
        register_timer=False,
    )

    ready_file = Path(args.ready_file)
    stop_file = Path(args.stop_file)
    ready_file.write_text("ready\n", encoding="utf-8")

    try:
        while not stop_file.exists():
            bridge._drain_command_queue()  # noqa: SLF001
            time.sleep(0.02)
    finally:
        bridge.stop_bridge()


if __name__ == "__main__":
    main()
