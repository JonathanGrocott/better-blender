"""Main-thread collections commands. Shared validation and helpers come from the bridge context."""

from __future__ import annotations

import bpy

METHODS = frozenset(
    [
        "list_collections",
        "create_collection",
        "add_object_to_collection",
        "remove_object_from_collection",
        "list_view_layers",
        "set_active_view_layer",
        "set_collection_visibility",
    ]
)


def dispatch(method, params, bridge):
    if method == "list_collections":
        collections = [
            {"name": collection.name, "objects_total": len(collection.objects)}
            for collection in bpy.data.collections
        ]
        return {"collections": collections, "count": len(collections)}

    if method == "create_collection":
        name = params.get("name")
        parent_name = params.get("parent_name")
        link_to_scene = bool(params.get("link_to_scene", True))

        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        if bpy.data.collections.get(name) is not None:
            raise ValueError(f"Collection already exists: {name}")

        collection = bpy.data.collections.new(name)
        if isinstance(parent_name, str) and parent_name:
            parent = bridge._require_collection(parent_name)
            parent.children.link(collection)
        elif link_to_scene:
            bpy.context.scene.collection.children.link(collection)

        return {"collection": {"name": collection.name, "objects_total": len(collection.objects)}}

    if method == "add_object_to_collection":
        object_name = params.get("object_name")
        collection_name = params.get("collection_name")
        unlink_from_others = bool(params.get("unlink_from_others", False))

        obj = bridge._require_object(object_name)
        collection = bridge._require_collection(collection_name)

        if obj.name not in collection.objects:
            collection.objects.link(obj)

        if unlink_from_others:
            for candidate in bpy.data.collections:
                if candidate.name != collection.name and obj.name in candidate.objects:
                    candidate.objects.unlink(obj)

        return {
            "object_name": obj.name,
            "collection_name": collection.name,
            "unlink_from_others": unlink_from_others,
        }

    if method == "remove_object_from_collection":
        object_name = params.get("object_name")
        collection_name = params.get("collection_name")
        obj = bridge._require_object(object_name)
        collection = bridge._require_collection(collection_name)

        if obj.name not in collection.objects:
            raise ValueError(f"Object {obj.name} is not linked to collection {collection.name}")

        collection.objects.unlink(obj)
        return {"object_name": obj.name, "collection_name": collection.name}

    if method == "list_view_layers":
        scene = bpy.context.scene
        active = bpy.context.view_layer.name
        layers = [{"name": view_layer.name} for view_layer in scene.view_layers]
        return {"view_layers": layers, "active_view_layer": active, "count": len(layers)}

    if method == "set_active_view_layer":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        view_layer = bridge._require_view_layer(name)
        window = bpy.context.window
        if window is None:
            raise RuntimeError("No active window available to set view layer")
        window.view_layer = view_layer
        return {"active_view_layer": view_layer.name}

    if method == "set_collection_visibility":
        collection_name = params.get("collection_name")
        collection = bridge._require_collection(collection_name)
        view_layer_name = params.get("view_layer_name")
        resolved_view_layer_name = view_layer_name if isinstance(view_layer_name, str) else None
        view_layer = bridge._require_view_layer(resolved_view_layer_name)

        hide_viewport = params.get("hide_viewport")
        hide_render = params.get("hide_render")
        exclude = params.get("exclude")
        holdout = params.get("holdout")
        indirect_only = params.get("indirect_only")

        layer_collection = bridge._find_layer_collection(
            view_layer.layer_collection, collection.name
        )
        if layer_collection is None:
            raise ValueError(
                f"Collection {collection.name} is not present in view layer {view_layer.name}"
            )

        if isinstance(hide_viewport, bool):
            collection.hide_viewport = hide_viewport
        if isinstance(hide_render, bool):
            collection.hide_render = hide_render

        if isinstance(exclude, bool):
            layer_collection.exclude = exclude
        if isinstance(holdout, bool):
            layer_collection.holdout = holdout
        if isinstance(indirect_only, bool):
            layer_collection.indirect_only = indirect_only

        return {
            "collection_name": collection.name,
            "view_layer_name": view_layer.name,
            "hide_viewport": collection.hide_viewport,
            "hide_render": collection.hide_render,
            "exclude": layer_collection.exclude,
            "holdout": layer_collection.holdout,
            "indirect_only": layer_collection.indirect_only,
        }
    raise ValueError(f"Unsupported collections method: {method}")
