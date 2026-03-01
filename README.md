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
  - Animation/Actions: `keyframe_transform`, `insert_keyframe`, `list_animation_data`, `list_actions`, `create_action`, `set_active_action`, `push_down_action`, `clear_animation_data`
  - Modifiers/Constraints: `add_modifier`, `list_modifiers`, `apply_modifier`, `remove_modifier`, `add_constraint`, `list_constraints`, `remove_constraint`
  - Geometry Nodes: `create_geometry_nodes_modifier`, `list_geometry_nodes`, `add_geometry_node`, `link_geometry_nodes`
  - Materials: `create_material`, `assign_material`
  - Camera/Light: `create_camera`, `set_active_camera`, `create_light`
  - Compositor/Passes: `enable_compositor`, `list_compositor_nodes`, `add_compositor_node`, `link_compositor_nodes`, `set_view_layer_passes`
  - Rendering: `render_still`, `render_animation`
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
better-blender-mcp install-addon --blender-version 4.2
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

### 5) Run diagnostics
```bash
better-blender-mcp doctor
```

## Commands
- `better-blender-mcp serve`: run MCP server over stdio.
- `better-blender-mcp doctor`: print environment diagnostics.
- `better-blender-mcp print-config --client <target>`: print MCP config snippet.
- `better-blender-mcp install-addon --blender-version <major.minor>`: copy add-on into user scripts directory.

## Docs
- Implementation milestones: `docs/milestone-board.md`
- Bridge and protocol specification: `docs/spec.md`
- Blender API alignment map: `docs/blender-api-alignment.md`

## Development checks
```bash
ruff check .
mypy src
pytest
```

## Headless integration tests
- Local: `pytest -m integration`
- CI: `.github/workflows/ci.yml` includes `integration-blender` job that installs Blender and runs end-to-end bridge/operator tests.
