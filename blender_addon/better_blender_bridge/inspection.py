"""Read-only scene and node inspection."""

import math

import bpy
from mathutils import Vector


def value_json(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bpy.types.ID):
        return {"name": value.name, "type": value.bl_rna.identifier}
    if hasattr(value, "__iter__"):
        return [value_json(item) for item in value]
    return None


def properties(owner):
    result = []
    for prop in owner.bl_rna.properties:
        if prop.is_readonly or prop.type == "COLLECTION" or prop.identifier == "rna_type":
            continue
        try:
            item = {
                "name": prop.identifier,
                "type": prop.type,
                "value": value_json(getattr(owner, prop.identifier)),
                "description": prop.description,
            }
            if prop.type == "ENUM":
                item["choices"] = [entry.identifier for entry in prop.enum_items]
            if prop.type in {"INT", "FLOAT"}:
                item["minimum"] = prop.hard_min
                item["maximum"] = prop.hard_max
            result.append(item)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            continue
    return result


def object_details(obj, evaluated=False):
    bpy.context.view_layer.update()
    result = {
        "parent": obj.parent.name if obj.parent else None,
        "parent_type": obj.parent_type,
        "collections": sorted(c.name for c in obj.users_collection),
        "matrix_world": [list(row) for row in obj.matrix_world],
        "hide_viewport": obj.hide_viewport,
        "hide_render": obj.hide_render,
        "visible": obj.visible_get() if obj.name in bpy.context.view_layer.objects else False,
    }
    if evaluated:
        evaluated_object = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        corners = [evaluated_object.matrix_world @ Vector(c) for c in evaluated_object.bound_box]
        result["evaluated_world_bounds"] = (
            {
                "min": [min(point[i] for point in corners) for i in range(3)],
                "max": [max(point[i] for point in corners) for i in range(3)],
            }
            if obj.type in {"MESH", "CURVE", "SURFACE", "FONT", "META", "VOLUME"}
            else None
        )
    return result


def node_details(tree, name):
    node = tree.nodes.get(name)
    if node is None:
        raise ValueError(f"Node not found: {name}")

    def sockets(items):
        return [
            {
                "index": index,
                "name": socket.name,
                "identifier": socket.identifier,
                "type": socket.bl_idname,
                "linked": socket.is_linked,
                "default_value": value_json(getattr(socket, "default_value", None)),
            }
            for index, socket in enumerate(items)
        ]

    return {
        "name": node.name,
        "type": node.bl_idname,
        "inputs": sockets(node.inputs),
        "outputs": sockets(node.outputs),
        "properties": properties(node),
    }
