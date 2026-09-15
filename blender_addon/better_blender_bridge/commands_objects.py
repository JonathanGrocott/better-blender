"""Main-thread objects commands. Shared validation and helpers come from the bridge context."""

from __future__ import annotations

import bpy

from . import inspection

METHODS = frozenset(
    [
        "list_objects",
        "get_object_info",
        "create_primitive",
        "delete_object",
        "set_object_transform",
        "duplicate_object",
        "add_modifier",
        "list_modifiers",
        "apply_modifier",
        "remove_modifier",
        "add_constraint",
        "list_constraints",
        "remove_constraint",
        "create_material",
        "assign_material",
    ]
)


def dispatch(method, params, bridge):
    if method == "list_objects":
        query = params.get("query", "").casefold()
        object_type = params.get("object_type")
        collection = params.get("collection_name")
        if collection is not None:
            bridge._require_collection(collection)
        matches = sorted(
            (
                obj
                for obj in bpy.context.scene.objects
                if query in obj.name.casefold()
                and (not object_type or obj.type == object_type.upper())
                and (collection is None or collection in {c.name for c in obj.users_collection})
            ),
            key=lambda obj: obj.name,
        )
        offset, limit = params.get("offset", 0), params.get("limit", 100)
        objects = [bridge._serialize_object(obj) for obj in matches[offset : offset + limit]]
        return {
            "objects": objects,
            "count": len(objects),
            "total": len(matches),
            "next_offset": offset + limit if offset + limit < len(matches) else None,
        }

    if method == "get_object_info":
        obj = bridge._require_object(params.get("name"))
        return {
            "object": {
                **bridge._serialize_object(obj),
                **inspection.object_details(obj, params.get("evaluated", False)),
            }
        }

    if method == "create_primitive":
        bridge._require_object_mode()
        primitive = params.get("primitive", "CUBE")
        if not isinstance(primitive, str):
            raise ValueError("primitive must be a string")

        primitive = primitive.upper()
        name = params.get("name")
        location = bridge._to_vector3(params.get("location", [0.0, 0.0, 0.0]), "location")
        rotation = bridge._to_vector3(params.get("rotation", [0.0, 0.0, 0.0]), "rotation")
        scale = bridge._to_vector3(params.get("scale", [1.0, 1.0, 1.0]), "scale")
        size = float(params.get("size", 2.0))

        if primitive == "CUBE":
            bpy.ops.mesh.primitive_cube_add(
                size=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "UV_SPHERE":
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=size / 2,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "ICO_SPHERE":
            bpy.ops.mesh.primitive_ico_sphere_add(
                radius=size / 2,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "CYLINDER":
            bpy.ops.mesh.primitive_cylinder_add(
                radius=size / 2,
                depth=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "CONE":
            bpy.ops.mesh.primitive_cone_add(
                radius1=size / 2,
                depth=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "PLANE":
            bpy.ops.mesh.primitive_plane_add(
                size=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "TORUS":
            bpy.ops.mesh.primitive_torus_add(
                major_radius=size / 2,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        elif primitive == "MONKEY":
            bpy.ops.mesh.primitive_monkey_add(
                size=size,
                location=location,
                rotation=rotation,
                scale=scale,
            )
        else:
            raise ValueError(f"Unsupported primitive: {primitive}")

        obj = bpy.context.active_object
        if obj is None:
            raise RuntimeError("Primitive creation did not produce an active object")

        if isinstance(name, str) and name:
            obj.name = name

        return {"object": bridge._serialize_object(obj)}

    if method == "delete_object":
        obj = bridge._require_object(params.get("name"))
        deleted_name = obj.name
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"deleted": deleted_name}

    if method == "set_object_transform":
        obj = bridge._require_object(params.get("name"))

        if "location" in params:
            obj.location = bridge._to_vector3(params["location"], "location")
        if "rotation" in params:
            obj.rotation_euler = bridge._to_vector3(params["rotation"], "rotation")
        if "scale" in params:
            obj.scale = bridge._to_vector3(params["scale"], "scale")

        return {"object": bridge._serialize_object(obj)}

    if method == "duplicate_object":
        bridge._require_object_mode()
        obj = bridge._require_object(params.get("name"))
        new_name = params.get("new_name")
        linked = bool(params.get("linked", False))

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.duplicate(linked=linked)

        duplicated = bpy.context.active_object
        if duplicated is None:
            raise RuntimeError("Duplicate operation did not return an active object")

        if isinstance(new_name, str) and new_name:
            duplicated.name = new_name

        return {"object": bridge._serialize_object(duplicated)}

    if method == "add_modifier":
        obj = bridge._require_object(params.get("object_name"))
        modifier_type = params.get("modifier_type")
        name = params.get("name")

        if not isinstance(modifier_type, str) or not modifier_type:
            raise ValueError("modifier_type must be a non-empty string")

        modifier_name = name if isinstance(name, str) and name else modifier_type.title()
        modifier = obj.modifiers.new(name=modifier_name, type=modifier_type.upper())

        settings = params.get("settings")
        try:
            if isinstance(settings, dict):
                for key in settings:
                    prop = modifier.bl_rna.properties.get(key)
                    if prop is None or prop.is_readonly:
                        raise ValueError(f"Unknown or read-only modifier setting: {key}")
                for key, value in settings.items():
                    setattr(modifier, key, value)
        except Exception:
            obj.modifiers.remove(modifier)
            raise

        return {
            "object_name": obj.name,
            "modifier": {"name": modifier.name, "type": modifier.type},
            "modifiers_total": len(obj.modifiers),
        }

    if method == "list_modifiers":
        obj = bridge._require_object(params.get("object_name"))
        modifiers = [{"name": mod.name, "type": mod.type} for mod in obj.modifiers]
        return {"object_name": obj.name, "modifiers": modifiers, "count": len(modifiers)}

    if method == "apply_modifier":
        obj = bridge._require_object(params.get("object_name"))
        modifier_name = params.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            raise ValueError("modifier_name must be a non-empty string")

        if obj.modifiers.get(modifier_name) is None:
            raise ValueError(f"Modifier not found: {modifier_name}")

        bridge._set_active_object(obj)
        bpy.ops.object.modifier_apply(modifier=modifier_name)
        return {"object_name": obj.name, "applied_modifier": modifier_name}

    if method == "remove_modifier":
        obj = bridge._require_object(params.get("object_name"))
        modifier_name = params.get("modifier_name")
        if not isinstance(modifier_name, str) or not modifier_name:
            raise ValueError("modifier_name must be a non-empty string")

        modifier = obj.modifiers.get(modifier_name)
        if modifier is None:
            raise ValueError(f"Modifier not found: {modifier_name}")

        obj.modifiers.remove(modifier)
        return {"object_name": obj.name, "removed_modifier": modifier_name}

    if method == "add_constraint":
        obj = bridge._require_object(params.get("object_name"))
        constraint_type = params.get("constraint_type")
        constraint_name = params.get("name")
        target_name = params.get("target_name")

        if not isinstance(constraint_type, str) or not constraint_type:
            raise ValueError("constraint_type must be a non-empty string")

        constraint = obj.constraints.new(type=constraint_type.upper())
        if isinstance(constraint_name, str) and constraint_name:
            constraint.name = constraint_name

        if isinstance(target_name, str) and target_name:
            target = bridge._require_object(target_name)
            if hasattr(constraint, "target"):
                constraint.target = target

        return {
            "object_name": obj.name,
            "constraint": {"name": constraint.name, "type": constraint.type},
            "constraints_total": len(obj.constraints),
        }

    if method == "list_constraints":
        obj = bridge._require_object(params.get("object_name"))
        constraints = []
        for constraint in obj.constraints:
            constraints.append(
                {
                    "name": constraint.name,
                    "type": constraint.type,
                    "target": constraint.target.name
                    if hasattr(constraint, "target") and constraint.target is not None
                    else None,
                }
            )
        return {"object_name": obj.name, "constraints": constraints, "count": len(constraints)}

    if method == "remove_constraint":
        obj = bridge._require_object(params.get("object_name"))
        constraint_name = params.get("constraint_name")
        if not isinstance(constraint_name, str) or not constraint_name:
            raise ValueError("constraint_name must be a non-empty string")

        constraint = obj.constraints.get(constraint_name)
        if constraint is None:
            raise ValueError(f"Constraint not found: {constraint_name}")

        obj.constraints.remove(constraint)
        return {"object_name": obj.name, "removed_constraint": constraint_name}

    if method == "create_material":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        base_color_raw = params.get("base_color", [0.8, 0.8, 0.8, 1.0])
        if not isinstance(base_color_raw, list) or len(base_color_raw) != 4:
            raise ValueError("base_color must be a list of 4 numbers")

        base_color = [float(v) for v in base_color_raw]
        roughness = float(params.get("roughness", 0.5))
        metallic = float(params.get("metallic", 0.0))

        material = bpy.data.materials.get(name)
        if material is None:
            material = bpy.data.materials.new(name=name)

        material.use_nodes = True
        nodes = material.node_tree.nodes
        principled = nodes.get("Principled BSDF")
        if principled is None:
            raise RuntimeError("Principled BSDF node not found")

        principled.inputs["Base Color"].default_value = base_color
        principled.inputs["Roughness"].default_value = roughness
        principled.inputs["Metallic"].default_value = metallic

        return {
            "material": {
                "name": material.name,
                "base_color": base_color,
                "roughness": roughness,
                "metallic": metallic,
            }
        }

    if method == "assign_material":
        object_name = params.get("object_name")
        material_name = params.get("material_name")

        obj = bridge._require_object(object_name)
        if not isinstance(material_name, str) or not material_name:
            raise ValueError("material_name must be a non-empty string")

        material = bpy.data.materials.get(material_name)
        if material is None:
            raise ValueError(f"Material not found: {material_name}")

        if not hasattr(obj.data, "materials"):
            raise ValueError(f"Object type {obj.type} does not support materials")

        slot_index = params.get("slot_index")
        materials = obj.data.materials

        if isinstance(slot_index, int) and slot_index >= 0 and slot_index < len(materials):
            materials[slot_index] = material
        else:
            materials.append(material)

        return {"object": bridge._serialize_object(obj)}
    raise ValueError(f"Unsupported objects method: {method}")
