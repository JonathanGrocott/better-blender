"""Validate the generated MCP input schemas without third-party Blender dependencies."""

import json
import math
from pathlib import Path

SCHEMAS = json.loads(Path(__file__).with_name("schemas.json").read_text())


def validate(value, schema, path="params"):
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                validate(value, choice, path)
                return
            except ValueError:
                pass
        raise ValueError(f"{path} does not match its allowed types or bounds")
    kind = schema.get("type")
    valid = {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": type(value) is int,
        "number": type(value) in (int, float) and math.isfinite(value),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }
    if kind and not valid.get(kind, False):
        raise ValueError(f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}")
    if kind == "number" or kind == "integer":
        for key, invalid in [
            ("minimum", lambda x: value < x),
            ("maximum", lambda x: value > x),
            ("exclusiveMinimum", lambda x: value <= x),
            ("exclusiveMaximum", lambda x: value >= x),
        ]:
            if key in schema and invalid(schema[key]):
                raise ValueError(f"{path} violates {key}={schema[key]}")
    if kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ValueError(f"{path} has invalid length")
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    if kind == "object":
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"Unknown parameter {path}.{key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(item, schema["additionalProperties"], f"{path}.{key}")


def validate_command(method, params):
    if method not in SCHEMAS:
        raise ValueError(f"Unsupported method: {method}")
    validate(params, SCHEMAS[method])
