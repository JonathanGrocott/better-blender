# Blender API Alignment

This project aligns MCP tool design with Blender's API organization described in the Blender API overview:
- `bpy.context`: access active scene and current state.
- `bpy.data`: read and create Blender data-blocks.
- `bpy.ops`: perform operator actions (file, mesh, render, import/export).

## Implemented Coverage

## Context-based workflows (`bpy.context`)
- `get_scene_info`
- `list_objects`
- `list_collections`
- `set_active_camera`

## Data-block workflows (`bpy.data`)
- `get_object_info`
- `create_material`
- `assign_material`
- `create_camera`
- `create_light`

## Operator workflows (`bpy.ops`)
- File lifecycle: `new_scene`, `open_blend`, `save_blend`
- Mesh/object actions: `create_primitive`, `delete_object`, `duplicate_object`, `set_object_transform`
- Rendering: `render_still`
- Import/export: `import_file`, `export_file`

## Advanced scripting
- `execute_blender_code` -> `execute_code` bridge method (explicitly gated behind add-on preference `allow_unsafe_code`)

## Current Gaps vs Full Blender Surface
- Animation/keyframes and timeline automation.
- Geometry nodes and modifiers management.
- Constraints, parenting, and rigging tools.
- Compositor nodes and render passes.
- Collection linking across scenes and view layers.
- Asset browser operations.

These will be added incrementally in upcoming milestones.
