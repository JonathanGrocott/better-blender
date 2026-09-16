# better-blender

Better Blender is a local-first MCP server and Blender add-on bridge for automating Blender through MCP clients.

## Current status
This repository now includes:
- `better-blender-mcp` Python package with CLI and MCP server entrypoint.
- `better_blender_bridge` Blender add-on with an authenticated socket bridge.
- Implemented MCP tools:
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

## Install a release (recommended)

Download from [Latest release](https://github.com/JonathanGrocott/better-blender/releases/latest).
The **Python wheel** installs the MCP server and includes the matching Blender
add-on. The separate **add-on ZIP** is for manual Blender installation; GitHub's
**Source code** archives are for developers.

Follow [Installing a release](docs/installing-releases.md) for Windows/macOS/Linux
instructions, checksum verification, client configuration, upgrades and rollback.
No source checkout is needed.

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

Copy the generated JSON into your MCP client config. Installation creates a unique token shared with Blender; leave the add-on’s **Token override** blank. Existing custom tokens remain supported when configured on both sides.

For full client-specific setup (Claude Desktop, VS Code GitHub Copilot, VS Code Continue, Codex), see `docs/client-setup.md`.

### 5) Run diagnostics
```bash
better-blender-mcp doctor
```

## Commands
- `better-blender-mcp setup`: create the shared per-user token.
- `better-blender-mcp serve`: run MCP server over stdio.
- `better-blender-mcp doctor`: print environment diagnostics.
- `better-blender-mcp print-config --client <target>`: print MCP config snippet.
- `better-blender-mcp install-addon --blender-version <major.minor[.patch]>`: copy add-on into user scripts directory.

## Docs
- Implementation milestones: `docs/milestone-board.md`
- Bridge and protocol specification: `docs/spec.md`
- Blender API alignment map: `docs/blender-api-alignment.md`
- Client setup guide: `docs/client-setup.md`
- Release installation: [Installing a release](docs/installing-releases.md)
- Maintainer release process: [Publishing a release](docs/releasing.md)

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


## Recovery, inspection and distributions (0.4)

- Use `create_checkpoint` before editing and `restore_checkpoint` to recover. Restores
  open a separate working copy and back up your current document by default.
  `run_with_checkpoint` provides the same recovery point around destructive operations.
- `list_objects` supports filtering and pagination. `get_object_info` includes parenting,
  world transforms, visibility and optional evaluated bounds; `get_node_info` exposes
  sockets and editable properties for geometry, material and compositor nodes.
- `list_jobs` shows progress and recent history across bridge restarts. `get_job_image`
  retrieves completed PNG/JPEG outputs directly in MCP.
- Installation stages the replacement before moving the previous add-on, and restores
  the previous version if activation fails. Windows and macOS installation checks run in CI.
- Successful CI runs publish **better-blender-distributions**, containing an unsigned
  wheel, Blender add-on ZIP, and SHA256SUMS. Download it from the run's Artifacts section.
  These development artifacts expire after 30 days. Version tags also publish the
  files to [GitHub Releases](https://github.com/JonathanGrocott/better-blender/releases).
  Build the same artifacts locally with `python scripts/build_artifacts.py`.
- CI launches a real Blender window under Xvfb for all supported Blender versions,
  checking enable/disable, restart, file-load timers, and OpenGL viewport capture.


## Safer operations and diagnostics (0.5)

- Document/session IDs prevent queued edits from crossing file or scene switches.
- `execute_request` and `get_request_status` provide durable, at-most-once edit
  admission and outcome lookup after disconnects or restarts.
- Generated credentials, read-only mode, optional tool-path restrictions and
  explicit nonlocal binding opt-in are available in setup/add-on preferences.
- Checkpoints have deletion, count/byte retention limits and disk usage reporting.
  External asset checks run before render submission and checkpoint restore.
- `get_diagnostics` exposes queue/worker state, recent failures and rotating
  structured logs. The dispatcher is split into six domain modules.

See [Operations](docs/operations.md) for retry semantics, migration from the old
`change-me` token, storage limits and the scope of path/asset checks.

### Lifecycle reliability (0.5.1)

Render workers now have independent supervision, a configurable runtime limit
(default one hour), and cleanup after bridge crashes. Failed job admission starts
no worker; cancellation remains available during storage failures. Bridge startup
rolls back partial initialization, and shutdown closes database/log resources after
request handlers finish. See [Operations](docs/operations.md#render-and-bridge-lifecycle-051).
