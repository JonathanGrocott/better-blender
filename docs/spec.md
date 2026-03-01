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
- `render_still`
- `render_animation`
- `import_file`
- `export_file`
- `execute_code` (requires add-on preference `allow_unsafe_code=true`)

## Error Semantics
- `Unauthorized`: token mismatch.
- `Invalid request envelope`: missing/invalid `id` or `method`.
- `params must be an object`: params not JSON object.
- `Unsupported method: <method>`: unknown command.
- `Request timed out`: command did not complete before timeout.

## Compatibility Policy
- Major versions can introduce breaking envelope or method changes.
- Minor versions add methods/fields without breaking existing clients.

## Next Spec Iterations
- Long-running jobs (`job_id`, poll/cancel methods).
- Safe mode policy matrix (`read_only`, `normal`, `unsafe`).
- Optional stream transport and event subscriptions.
