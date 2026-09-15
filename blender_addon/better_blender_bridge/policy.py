"""Conservative method classification and optional tool-path restrictions."""

from pathlib import Path

READ_METHODS = frozenset(
    {
        "health",
        "get_document_context",
        "get_request_status",
        "get_diagnostics",
        "get_scene_info",
        "list_objects",
        "get_object_info",
        "list_materials",
        "list_collections",
        "list_view_layers",
        "list_modifiers",
        "list_constraints",
        "list_actions",
        "list_nla_tracks",
        "list_geometry_inputs",
        "list_geometry_nodes",
        "list_compositor_nodes",
        "list_checkpoints",
        "get_job_status",
        "list_jobs",
        "get_job_image",
        "get_checkpoint_usage",
        "check_assets",
        "get_node_info",
        "list_animation_data",
        "get_node_details",
        "get_object_details",
    }
)


def check_path(path, roots):
    resolved = Path(path).expanduser().resolve()
    if roots and not any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError("Path is outside the configured allowed directories")
    return resolved
