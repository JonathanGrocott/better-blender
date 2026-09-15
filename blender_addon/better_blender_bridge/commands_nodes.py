"""Main-thread nodes commands. Shared validation and helpers come from the bridge context."""

from __future__ import annotations

from typing import Any

import bpy

from . import inspection

METHODS = frozenset(
    [
        "get_node_info",
        "create_geometry_nodes_modifier",
        "list_geometry_nodes",
        "add_geometry_node",
        "link_geometry_nodes",
        "add_geometry_input",
        "list_geometry_inputs",
        "set_geometry_input",
        "enable_compositor",
        "list_compositor_nodes",
        "add_compositor_node",
        "link_compositor_nodes",
    ]
)


def dispatch(method, params, bridge):
    if method == "get_node_info":
        tree_type = params.get("tree_type", "GEOMETRY")
        if tree_type == "GEOMETRY":
            obj = bridge._require_object(params.get("object_name"))
            modifier = bridge._require_modifier(obj, params.get("modifier_name", "GeometryNodes"))
            tree = modifier.node_group if modifier.type == "NODES" else None
        elif tree_type == "MATERIAL":
            tree = bridge._require_material(params.get("material_name")).node_tree
        else:
            tree = bridge._require_node_tree(bpy.context.scene)
        if tree is None:
            raise ValueError("Node tree is not configured")
        return inspection.node_details(tree, params["node_name"])

    if method == "create_geometry_nodes_modifier":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")

        obj = bridge._require_object(object_name)
        if not isinstance(modifier_name, str) or not modifier_name:
            raise ValueError("modifier_name must be a non-empty string")

        modifier = obj.modifiers.get(modifier_name)
        if modifier is None:
            modifier = obj.modifiers.new(name=modifier_name, type="NODES")
        elif modifier.type != "NODES":
            raise ValueError(
                f"Modifier {modifier_name} exists but is not a geometry nodes modifier"
            )

        node_group = bridge._ensure_geometry_nodes_group(modifier)
        return {
            "object_name": obj.name,
            "modifier": {"name": modifier.name, "type": modifier.type},
            "node_group": node_group.name,
        }

    if method == "list_geometry_nodes":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        obj = bridge._require_object(object_name)
        modifier = bridge._require_modifier(obj, modifier_name)

        if modifier.type != "NODES" or modifier.node_group is None:
            raise ValueError(
                f"Modifier {modifier.name} is not configured with a geometry node tree"
            )

        node_group = modifier.node_group
        nodes = [{"name": node.name, "type": node.bl_idname} for node in node_group.nodes]
        links = []
        for link in node_group.links:
            links.append(
                {
                    "from_node": link.from_node.name,
                    "from_socket": link.from_socket.name,
                    "to_node": link.to_node.name,
                    "to_socket": link.to_socket.name,
                }
            )

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "node_group": node_group.name,
            "nodes": nodes,
            "links": links,
        }

    if method == "add_geometry_node":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        node_type = params.get("node_type")
        node_name = params.get("node_name")

        obj = bridge._require_object(object_name)
        modifier = bridge._require_modifier(obj, modifier_name)

        if modifier.type != "NODES":
            raise ValueError(f"Modifier {modifier.name} is not a geometry nodes modifier")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError("node_type must be a non-empty string")

        node_group = bridge._ensure_geometry_nodes_group(modifier)
        node = node_group.nodes.new(node_type)
        if isinstance(node_name, str) and node_name:
            node.name = node_name

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "node": {"name": node.name, "type": node.bl_idname},
        }

    if method == "link_geometry_nodes":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        from_node_name = params.get("from_node")
        from_socket_name = params.get("from_socket")
        to_node_name = params.get("to_node")
        to_socket_name = params.get("to_socket")

        obj = bridge._require_object(object_name)
        modifier = bridge._require_modifier(obj, modifier_name)
        if modifier.type != "NODES":
            raise ValueError(f"Modifier {modifier.name} is not a geometry nodes modifier")

        for field_name, value in (
            ("from_node", from_node_name),
            ("from_socket", from_socket_name),
            ("to_node", to_node_name),
            ("to_socket", to_socket_name),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")

        node_group = bridge._ensure_geometry_nodes_group(modifier)
        from_node = node_group.nodes.get(from_node_name)
        to_node = node_group.nodes.get(to_node_name)
        if from_node is None:
            raise ValueError(f"Node not found: {from_node_name}")
        if to_node is None:
            raise ValueError(f"Node not found: {to_node_name}")

        from_socket = from_node.outputs.get(from_socket_name)
        to_socket = to_node.inputs.get(to_socket_name)
        if from_socket is None:
            raise ValueError(f"Socket not found: {from_node_name}.{from_socket_name}")
        if to_socket is None:
            raise ValueError(f"Socket not found: {to_node_name}.{to_socket_name}")

        node_group.links.new(from_socket, to_socket)
        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "linked": {
                "from_node": from_node.name,
                "from_socket": from_socket.name,
                "to_node": to_node.name,
                "to_socket": to_socket.name,
            },
        }

    if method == "add_geometry_input":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        input_name = params.get("input_name")
        socket_type = params.get("socket_type", "NodeSocketFloat")
        default_value = params.get("default_value")

        obj = bridge._require_object(object_name)
        modifier = bridge._require_modifier(obj, modifier_name)
        if modifier.type != "NODES":
            raise ValueError(f"Modifier {modifier.name} is not a geometry nodes modifier")
        if not isinstance(input_name, str) or not input_name:
            raise ValueError("input_name must be a non-empty string")
        if not isinstance(socket_type, str) or not socket_type:
            raise ValueError("socket_type must be a non-empty string")

        node_group = bridge._ensure_geometry_nodes_group(modifier)
        if hasattr(node_group, "interface"):
            socket = node_group.interface.new_socket(
                name=input_name,
                in_out="INPUT",
                socket_type=socket_type,
            )
            identifier = socket.identifier
            resolved_socket_type = socket.socket_type
        else:
            socket = node_group.inputs.new(socket_type, input_name)
            identifier = socket.identifier if hasattr(socket, "identifier") else socket.name
            resolved_socket_type = (
                socket.bl_socket_idname if hasattr(socket, "bl_socket_idname") else socket_type
            )

        if default_value is not None:
            stored_value: Any
            if isinstance(default_value, list):
                stored_value = tuple(default_value)
            else:
                stored_value = default_value
            modifier[identifier] = stored_value

        current = modifier.get(identifier)
        if hasattr(current, "__iter__") and not isinstance(current, (str, bytes, dict)):
            try:
                current = list(current)
            except TypeError:
                pass

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "input": {
                "name": input_name,
                "identifier": identifier,
                "socket_type": resolved_socket_type,
                "value": current,
            },
        }

    if method == "list_geometry_inputs":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        obj = bridge._require_object(object_name)
        modifier = bridge._require_modifier(obj, modifier_name)

        if modifier.type != "NODES" or modifier.node_group is None:
            raise ValueError(
                f"Modifier {modifier.name} is not configured with a geometry node tree"
            )

        inputs = []
        if hasattr(modifier.node_group, "interface"):
            for item in modifier.node_group.interface.items_tree:
                if item.item_type != "SOCKET" or item.in_out != "INPUT":
                    continue

                identifier = item.identifier
                value: Any = modifier.get(identifier)
                if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
                    try:
                        value = list(value)
                    except TypeError:
                        pass

                use_attr_key = f"{identifier}_use_attribute"
                attr_name_key = f"{identifier}_attribute_name"
                inputs.append(
                    {
                        "name": item.name,
                        "identifier": identifier,
                        "socket_type": item.socket_type,
                        "value": value,
                        "use_attribute": bool(modifier.get(use_attr_key, False)),
                        "attribute_name": modifier.get(attr_name_key, ""),
                    }
                )
        else:
            for socket in modifier.node_group.inputs:
                identifier = socket.identifier if hasattr(socket, "identifier") else socket.name
                value = modifier.get(identifier)
                if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
                    try:
                        value = list(value)
                    except TypeError:
                        pass
                use_attr_key = f"{identifier}_use_attribute"
                attr_name_key = f"{identifier}_attribute_name"
                inputs.append(
                    {
                        "name": socket.name,
                        "identifier": identifier,
                        "socket_type": getattr(socket, "bl_socket_idname", "UNKNOWN"),
                        "value": value,
                        "use_attribute": bool(modifier.get(use_attr_key, False)),
                        "attribute_name": modifier.get(attr_name_key, ""),
                    }
                )

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "inputs": inputs,
            "count": len(inputs),
        }

    if method == "set_geometry_input":
        object_name = params.get("object_name")
        modifier_name = params.get("modifier_name", "GeometryNodes")
        input_ref = params.get("input_name_or_identifier")
        value = params.get("value")
        use_attribute = params.get("use_attribute")
        attribute_name = params.get("attribute_name")

        obj = bridge._require_object(object_name)
        modifier = bridge._require_modifier(obj, modifier_name)
        if modifier.type != "NODES" or modifier.node_group is None:
            raise ValueError(
                f"Modifier {modifier.name} is not configured with a geometry node tree"
            )

        identifier, input_name = bridge._resolve_geometry_input_identifier(
            modifier.node_group, input_ref
        )

        if isinstance(value, list):
            cast_value: Any = tuple(value)
        else:
            cast_value = value

        if value is not None:
            modifier[identifier] = cast_value

        use_attr_key = f"{identifier}_use_attribute"
        attr_name_key = f"{identifier}_attribute_name"
        if isinstance(use_attribute, bool):
            modifier[use_attr_key] = use_attribute
        if isinstance(attribute_name, str):
            modifier[attr_name_key] = attribute_name

        current: Any = modifier.get(identifier)
        if hasattr(current, "__iter__") and not isinstance(current, (str, bytes, dict)):
            try:
                current = list(current)
            except TypeError:
                pass

        return {
            "object_name": obj.name,
            "modifier_name": modifier.name,
            "input": {
                "name": input_name,
                "identifier": identifier,
                "value": current,
                "use_attribute": bool(modifier.get(use_attr_key, False)),
                "attribute_name": modifier.get(attr_name_key, ""),
            },
        }

    if method == "enable_compositor":
        scene = bpy.context.scene
        use_nodes = bool(params.get("use_nodes", True))
        clear_nodes = bool(params.get("clear_nodes", False))
        if hasattr(scene, "use_nodes"):
            scene.use_nodes = use_nodes

        node_tree = bridge._get_or_create_compositor_tree(scene)

        if clear_nodes:
            node_tree.nodes.clear()
            render_layers = node_tree.nodes.new("CompositorNodeRLayers")
            if "Image" in render_layers.outputs:
                output = node_tree.nodes.new("CompositorNodeOutputFile")
                node_tree.links.new(render_layers.outputs["Image"], output.inputs[0])

        return {
            "use_nodes": bool(getattr(scene, "use_nodes", use_nodes)),
            "nodes_total": len(node_tree.nodes),
        }

    if method == "list_compositor_nodes":
        scene = bpy.context.scene
        node_tree = bridge._require_node_tree(scene)
        nodes = [{"name": node.name, "type": node.bl_idname} for node in node_tree.nodes]
        links = []
        for link in node_tree.links:
            links.append(
                {
                    "from_node": link.from_node.name,
                    "from_socket": link.from_socket.name,
                    "to_node": link.to_node.name,
                    "to_socket": link.to_socket.name,
                }
            )
        return {"nodes": nodes, "links": links, "count": len(nodes)}

    if method == "add_compositor_node":
        scene = bpy.context.scene
        node_tree = bridge._require_node_tree(scene)

        node_type = params.get("node_type")
        node_name = params.get("node_name")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError("node_type must be a non-empty string")

        node = node_tree.nodes.new(node_type)
        if isinstance(node_name, str) and node_name:
            node.name = node_name

        return {"node": {"name": node.name, "type": node.bl_idname}}

    if method == "link_compositor_nodes":
        scene = bpy.context.scene
        node_tree = bridge._require_node_tree(scene)

        from_node_name = params.get("from_node")
        from_socket_name = params.get("from_socket")
        to_node_name = params.get("to_node")
        to_socket_name = params.get("to_socket")

        for field_name, value in (
            ("from_node", from_node_name),
            ("from_socket", from_socket_name),
            ("to_node", to_node_name),
            ("to_socket", to_socket_name),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")

        from_node = node_tree.nodes.get(from_node_name)
        to_node = node_tree.nodes.get(to_node_name)
        if from_node is None:
            raise ValueError(f"Node not found: {from_node_name}")
        if to_node is None:
            raise ValueError(f"Node not found: {to_node_name}")

        from_socket = from_node.outputs.get(from_socket_name)
        to_socket = to_node.inputs.get(to_socket_name)
        if from_socket is None:
            raise ValueError(f"Socket not found: {from_node_name}.{from_socket_name}")
        if to_socket is None:
            raise ValueError(f"Socket not found: {to_node_name}.{to_socket_name}")

        node_tree.links.new(from_socket, to_socket)
        return {
            "linked": {
                "from_node": from_node.name,
                "from_socket": from_socket.name,
                "to_node": to_node.name,
                "to_socket": to_socket.name,
            }
        }
    raise ValueError(f"Unsupported nodes method: {method}")
