# Better Blender Bridge Specification (Draft v0.1)

## Scope
Defines the local protocol between:
- MCP server process (`better-blender-mcp`)
- Blender add-on bridge (`better_blender_bridge`)

## Transport
- Local TCP listener bound to `127.0.0.1` by default.
- Newline-delimited JSON request/response envelopes.
- One request per connection for v0.1.

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
- Request handlers only parse/validate and enqueue commands.
- Blender API work executes on main thread via timer callback (`bpy.app.timers`).
- Default bridge timeout is 30 seconds per request.
- Requests may include positive `timeout_seconds`; the smaller of this budget and the
  bridge timeout applies. The MCP client forwards its configured timeout and allows
  an additional second for the timeout response to arrive.
- Queued commands that expire are skipped without changing Blender state (`code: EXPIRED`).
- Commands already executing cannot be rolled back by a socket timeout. Their response
  uses `code: OUTCOME_UNKNOWN` and warns against automatic retries. Inspect scene/output
  state before deciding whether to retry. Rendering still executes synchronously in Blender.
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
at once. The bridge keeps 32 completed job records in memory; restart clears history
and stops workers. Temporary snapshots are removed after completion. Existing direct
bridge render methods remain synchronous for compatibility.
