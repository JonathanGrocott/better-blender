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

## Initial Methods
- `health`
- `get_scene_info`
- `list_objects`

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
