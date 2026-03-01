# Blender API Alignment

This project aligns MCP tool design with Blender's API organization described in the Blender API overview:
- `bpy.context`: access active scene and current state.
- `bpy.data`: read and create Blender data-blocks.
- `bpy.ops`: perform operator actions (file, mesh, render, import/export).

## Implemented Coverage

## Context-based workflows (`bpy.context`)
- `get_scene_info`
- `set_timeline`
- `list_objects`
- `list_collections`
- `list_view_layers`
- `set_active_camera`
- `set_active_view_layer`
- `set_collection_visibility`

## Data-block workflows (`bpy.data`)
- `get_object_info`
- `create_material`
- `assign_material`
- `create_camera`
- `create_light`
- `create_collection`
- `add_object_to_collection`
- `remove_object_from_collection`

## Operator workflows (`bpy.ops`)
- File lifecycle: `new_scene`, `open_blend`, `save_blend`
- Mesh/object actions: `create_primitive`, `delete_object`, `duplicate_object`, `set_object_transform`
- Modifier actions: `apply_modifier`
- Rendering: `render_still`
- Import/export: `import_file`, `export_file`

## Animation and rigging workflows
- `keyframe_transform`, `insert_keyframe`, `list_animation_data`
- `add_modifier`, `list_modifiers`, `remove_modifier`
- `add_constraint`, `list_constraints`, `remove_constraint`

## Advanced scripting
- `execute_blender_code` -> `execute_code` bridge method (explicitly gated behind add-on preference `allow_unsafe_code`)

## Current Gaps vs Full Blender Surface
- Geometry nodes node-tree authoring and advanced modifier parameter coverage.
- Rigging/bones, armature pose workflows, and IK setup helpers.
- Compositor nodes and render passes.
- Cross-scene collection linking and scene instancing helpers.
- Asset browser operations.

These will be added incrementally in upcoming milestones.
