# better-blender

Better Blender is a local-first MCP server and Blender add-on bridge for automating Blender through MCP clients.

## Current status
This repository now includes:
- `better-blender-mcp` Python package with CLI and MCP server entrypoint.
- `better_blender_bridge` Blender add-on skeleton with authenticated local socket bridge.
- Implemented MCP tools (first functional set):
  - System: `get_blender_status`
  - Scene/File: `new_scene`, `open_blend`, `save_blend`, `get_scene_info`, `set_timeline`
  - Collections/View Layers: `list_collections`, `create_collection`, `add_object_to_collection`, `remove_object_from_collection`, `list_view_layers`, `set_active_view_layer`, `set_collection_visibility`
  - Objects: `list_objects`, `get_object_info`, `create_primitive`, `delete_object`, `set_object_transform`, `duplicate_object`
  - Animation/Actions: `keyframe_transform`, `insert_keyframe`, `list_animation_data`, `list_actions`, `create_action`, `set_active_action`, `push_down_action`, `clear_animation_data`, `duplicate_action`, `delete_action`, `list_nla_tracks`, `create_nla_strip`, `set_nla_strip`, `remove_nla_strip`
  - Modifiers/Constraints: `add_modifier`, `list_modifiers`, `apply_modifier`, `remove_modifier`, `add_constraint`, `list_constraints`, `remove_constraint`
  - Geometry Nodes: `create_geometry_nodes_modifier`, `list_geometry_nodes`, `add_geometry_node`, `link_geometry_nodes`, `add_geometry_input`, `list_geometry_inputs`, `set_geometry_input`
  - Materials: `create_material`, `assign_material`
  - Camera/Light: `create_camera`, `set_active_camera`, `create_light`
  - Compositor/Passes: `enable_compositor`, `list_compositor_nodes`, `add_compositor_node`, `link_compositor_nodes`, `set_view_layer_passes`
  - Rendering: `render_still`, `render_animation`
  - View/Capture: `set_viewport_view`, `capture_viewport_screenshot`
  - High-level Workflows: `workflow_setup_studio`, `workflow_create_turntable`, `workflow_turntable_render`
  - I/O: `import_file`, `export_file`
  - Advanced: `execute_blender_code` (disabled by default, opt-in in add-on preferences)
- Milestone and protocol docs for completing a production implementation.

## Quickstart (developer)

### 1) Install package and dev tools
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### 2) Install Blender add-on files
```bash
better-blender-mcp install-addon --blender-version 3.4.1
```

### 3) Enable add-on in Blender
- Open Blender.
- Go to **Edit > Preferences > Add-ons**.
- Enable **Better Blender Bridge**.
- In 3D View sidebar, open **Better Blender** tab and click **Start Bridge**.

### 4) Configure MCP client
```bash
better-blender-mcp print-config --client claude-desktop
```

Copy generated JSON into your MCP client config and set `BETTER_BLENDER_TOKEN` to the same token configured in Blender add-on preferences.

For full client-specific setup (Claude Desktop, VS Code GitHub Copilot, VS Code Continue, Codex), see `docs/client-setup.md`.

### 5) Run diagnostics
```bash
better-blender-mcp doctor
```

## Commands
- `better-blender-mcp serve`: run MCP server over stdio.
- `better-blender-mcp doctor`: print environment diagnostics.
- `better-blender-mcp print-config --client <target>`: print MCP config snippet.
- `better-blender-mcp install-addon --blender-version <major.minor[.patch]>`: copy add-on into user scripts directory.

## Docs
- Implementation milestones: `docs/milestone-board.md`
- Bridge and protocol specification: `docs/spec.md`
- Blender API alignment map: `docs/blender-api-alignment.md`
- Client setup guide: `docs/client-setup.md`

## Development checks
```bash
ruff check .
mypy src
pytest
```

## Headless integration tests
- Local: `pytest -m integration`
- CI: `.github/workflows/ci.yml` includes `integration-blender` job that installs Blender and runs end-to-end bridge/operator tests.

## Reliable automation

- MCP render tools return a `job_id`. Use `get_job_status` to poll, and `cancel_job`
  to stop a worker. Renders use an isolated snapshot and do not modify the open scene.
  Two workers may run concurrently; cancellation retains any frames already written.
- Viewport capture returns an inline PNG image plus the saved path. Images over 8 MiB
  return the path and a request to reduce resolution instead of an oversized preview.
- Transform vectors have exactly three finite numbers. Euler rotations use radians.
  Invalid input and unknown modifier settings are rejected. Regenerate bridge schemas
  after editing tool signatures with `python scripts/update_tool_schemas.py`.
- `doctor` verifies the running bridge, authentication and protocol compatibility.
- Wheels include the Blender add-on; a source checkout is no longer required to install it.
- CI tests Blender 3.4.1, 4.2.0 and 5.0.1, including a real MCP stdio session.

After updating, reinstall the add-on and restart Blender and the MCP server so both
sides use the same protocol and schemas.
