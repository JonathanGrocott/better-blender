# Better Blender Bridge Specification (protocol 1, package 0.5)

## Scope
Defines the local protocol between:
- MCP server process (`better-blender-mcp`)
- Blender add-on bridge (`better_blender_bridge`)

## Transport
- Local TCP listener bound to `127.0.0.1` by default.
- Newline-delimited JSON request/response envelopes.
- One request per connection.

## Authentication
- Shared bearer token passed in each request body as `token`.
- Add-on rejects all requests with non-matching token.

## Request Envelope
```json
{
  "id": "uuid-string",
  "method": "get_scene_info",
  "params": {},
  "token": "secret"
}
```

## Response Envelope
Success:
```json
{
  "id": "uuid-string",
  "ok": true,
  "result": {
    "scene_name": "Scene"
  }
}
```

Failure:
```json
{
  "id": "uuid-string",
  "ok": false,
  "error": "Unauthorized"
}
```

## Command Execution Model
- Request handlers authenticate and enqueue Blender commands; job/status/diagnostic
  reads use thread-safe managers directly.
- Blender API work executes on main thread via timer callback (`bpy.app.timers`).
- Default bridge timeout is 30 seconds per request.
- Requests may include positive `timeout_seconds`; the smaller of this budget and the
  bridge timeout applies. The MCP client forwards its configured timeout and allows
  an additional second for the timeout response to arrive.
- Queued commands that expire are skipped without changing Blender state (`code: EXPIRED`).
- Commands already executing cannot be rolled back by a socket timeout. Their response
  uses `code: OUTCOME_UNKNOWN`. Query `get_request_status`; retry only with the same
  stable ID through `execute_request`. MCP rendering submits isolated worker jobs.
- MCP socket waits run off the event loop; Blender API work remains on its main thread.

## Implemented Methods (v0.2)
- `health`
- `new_scene`
- `open_blend`
- `save_blend`
- `get_scene_info`
- `set_timeline`
- `list_collections`
- `create_collection`
- `add_object_to_collection`
- `remove_object_from_collection`
- `list_view_layers`
- `set_active_view_layer`
- `set_collection_visibility`
- `list_objects`
- `get_object_info`
- `create_primitive`
- `delete_object`
- `set_object_transform`
- `duplicate_object`
- `keyframe_transform`
- `insert_keyframe`
- `list_animation_data`
- `list_actions`
- `create_action`
- `set_active_action`
- `push_down_action`
- `clear_animation_data`
- `duplicate_action`
- `delete_action`
- `list_nla_tracks`
- `create_nla_strip`
- `set_nla_strip`
- `remove_nla_strip`
- `create_geometry_nodes_modifier`
- `list_geometry_nodes`
- `add_geometry_node`
- `link_geometry_nodes`
- `add_geometry_input`
- `list_geometry_inputs`
- `set_geometry_input`
- `add_modifier`
- `list_modifiers`
- `apply_modifier`
- `remove_modifier`
- `add_constraint`
- `list_constraints`
- `remove_constraint`
- `create_material`
- `assign_material`
- `create_camera`
- `set_active_camera`
- `create_light`
- `enable_compositor`
- `list_compositor_nodes`
- `add_compositor_node`
- `link_compositor_nodes`
- `set_view_layer_passes`
- `set_viewport_view`
- `capture_viewport_screenshot`
- `render_still`
- `render_animation`
- `workflow_setup_studio`
- `workflow_create_turntable`
- `workflow_turntable_render`
- `import_file`
- `export_file`
- `execute_code` (requires add-on preference `allow_unsafe_code=true`)

## Error Semantics
- `Unauthorized`: token mismatch.
- `Invalid request envelope`: missing/invalid `id` or `method`.
- `params must be an object`: params not JSON object.
- `Unsupported method: <method>`: unknown command.
- `EXPIRED`: deadline elapsed before execution; no changes made.
- `OUTCOME_UNKNOWN`: deadline elapsed during execution; the operation may still complete.

## Compatibility Policy
- Major versions can introduce breaking envelope or method changes.
- Minor versions add methods/fields without breaking existing clients.

## Next Spec Iterations
- Long-running jobs (`job_id`, poll/cancel methods).
- Safe mode policy matrix (`read_only`, `normal`, `unsafe`).
- Optional stream transport and event subscriptions.

## Render jobs

MCP `render_still`, `render_animation`, and `workflow_turntable_render` now return a
`job_id` and state immediately after capturing the scene. Poll `get_job_status` for
`running`, `completed`, `failed`, `cancelling`, or `cancelled`, including result/error.
`cancel_job` terminates only the isolated render worker; partial output files remain.
The open scene and its file path are unchanged, including for turntable setup.
External assets must remain available while the job runs. Two render workers may run
at once. The bridge keeps 32 completed job records on disk; restart preserves history
and stops workers. Temporary snapshots are removed after completion. Existing direct
bridge render methods remain synchronous for compatibility.

## Resource limits and message validation

The bridge allows 16 simultaneous connections and 128 queued commands. Requests are
limited to 1 MiB and have a five-second read deadline; responses are limited to 16 MiB.
Excess capacity returns `BUSY`. The client uses buffered reads with an absolute deadline,
rejects truncated messages and validates response envelopes. Protocol/transport failures
have stable error codes on `BridgeError.code`. Screenshots carry at most 8 MiB of image
bytes before base64 encoding. Normal scene tool requests use generated strict input
schemas, with reference checks before mutation. These checks are not a transaction or
rollback guarantee for arbitrary Blender operator failures or unsafe Python execution.


## Recovery and inspection (0.4)

`create_checkpoint` saves a whole-file copy; `list_checkpoints` lists them newest first.
`restore_checkpoint` backs up the current document by default, then opens a separate
working copy beside the immutable snapshot. Use `save_blend` to choose a final path.
`run_with_checkpoint` wraps supported destructive scene/animation operations; failures
include the recovery checkpoint ID. Checkpoints are explicit snapshots, not automatic
transactions or copies of every external asset. Keep external assets available.

`list_objects` accepts a name substring, object type, collection, offset, and limit
(default 100, maximum 500). Results are sorted by name with total and next_offset.
Objects include parent, collection membership, visibility and matrix_world. Optional
`evaluated=true` on get_object_info adds world bounds after modifiers/dependencies.
`get_node_info` supports geometry, material and compositor trees and reports socket
identifiers, indices, types, defaults and writable RNA properties.

`list_jobs` includes persisted terminal history. `get_job_image` returns a recorded
PNG/JPEG output by index; arbitrary paths are not accepted. Render-write callbacks
report completed frames, total frames and progress fraction. There is no estimated
progress within a single frame. Up to 1,000 output paths are recorded per job.
Jobs interrupted by an unclean restart are marked interrupted; they are not resumed.

State is stored under ~/.better-blender, or BETTER_BLENDER_STATE_DIR when configured
in the Blender process environment. Job history is namespaced by bridge endpoint.
Checkpoint snapshots use count/byte retention limits (see below). Completed job history is bounded
to 32 records; render output files remain caller-owned and are never pruned.


## Targeting, retries and operations (0.5)

Requests may include `expected_document_id` (string). Successful response envelopes
also carry `document_id` and `session_id`. `get_document_context` returns these plus
the active scene and filepath. Mutations are rejected with `DOCUMENT_CHANGED` if
the active document differs at execution. Omitted IDs capture enqueue-time context.

Mutations are journaled using their envelope ID. Repeated IDs with identical method
and parameters replay the retained result or return `OUTCOME_UNKNOWN` while pending
or interrupted. Different arguments are rejected. `execute_request` carries a stable
ID as a parameter while preserving the outer MCP transport ID. Reads do not need
idempotency IDs. `get_request_status` returns `not_found`, `queued`, `running`,
`completed`, `expired`, or `interrupted`, with a retained response where available.
`completed` means dispatch finished; inspect its response's `ok` for success.

Additional tools: `get_diagnostics`, `delete_checkpoint`, `get_checkpoint_usage`,
`configure_checkpoint_retention`, and `check_assets`. Checkpoint defaults are 20
snapshots / 2 GiB; restored working copies are never pruned. `restore_checkpoint`
accepts `allow_missing_assets` for deliberate recovery with missing/unverified assets.

Authentication setup, access controls, journal bounds, logs, failure semantics and
asset-check limitations are specified in [Operations](operations.md).
