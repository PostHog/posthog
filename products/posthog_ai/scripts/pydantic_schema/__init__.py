"""Pydantic model introspection helpers for skill templates.

Provides functions to generate human-readable documentation (JSON schema,
Markdown tables, bullet lists) from Pydantic model classes, referenced by
their fully-qualified dotted path.
"""

from __future__ import annotations

import json
import importlib


def _import_model(dotted_path: str) -> type:
    """Import a class by its fully-qualified dotted path.

    Example: ``products.feature_flags.backend.max_tools.FeatureFlagCreationSchema``
    """
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ImportError(f"Invalid model path (need module.ClassName): {dotted_path}")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"{class_name} not found in {module_path}")
    return cls


def json_schema_type_label(prop: dict) -> str:
    """Derive a human-readable type label from a JSON Schema property."""
    if "anyOf" in prop:
        parts = []
        for option in prop["anyOf"]:
            parts.append(option.get("type", option.get("$ref", "?")))
        return " | ".join(parts)
    if "allOf" in prop:
        refs = [opt.get("$ref", "?") for opt in prop["allOf"]]
        return " & ".join(refs)
    t = prop.get("type", "any")
    if t == "array":
        items = prop.get("items", {})
        item_type = items.get("type", items.get("$ref", "any"))
        return f"array[{item_type}]"
    return t


def pydantic_schema(dotted_path: str, indent: int = 2) -> str:
    """Return the JSON Schema of a Pydantic model as a formatted JSON string.

    Usage in a template::

        ```json
        {{ pydantic_schema("products.feature_flags.backend.max_tools.FeatureFlagCreationSchema") }}
        ```
    """
    model_cls = _import_model(dotted_path)
    schema = model_cls.model_json_schema()
    return json.dumps(schema, indent=indent)


def pydantic_fields(dotted_path: str) -> str:
    """Return a Markdown table describing the fields of a Pydantic model.

    Columns: Field | Type | Required | Description

    Usage in a template::

        {{ pydantic_fields("products.feature_flags.backend.max_tools.FeatureFlagCreationSchema") }}
    """
    model_cls = _import_model(dotted_path)
    schema = model_cls.model_json_schema()
    required_set = set(schema.get("required", []))
    properties = schema.get("properties", {})

    rows: list[str] = []
    rows.append("| Field | Type | Required | Description |")
    rows.append("|-------|------|----------|-------------|")

    for name, prop in properties.items():
        field_type = json_schema_type_label(prop)
        required = "yes" if name in required_set else "no"
        description = prop.get("description", "").replace("\n", " ").replace("|", "\\|")
        rows.append(f"| `{name}` | {field_type} | {required} | {description} |")

    return "\n".join(rows)


def pydantic_field_list(dotted_path: str) -> str:
    """Return a bullet list of field names with their types.

    Usage in a template::

        {{ pydantic_field_list("products.surveys.backend.max_tools.CreateTemplateArgs") }}
    """
    model_cls = _import_model(dotted_path)
    schema = model_cls.model_json_schema()
    properties = schema.get("properties", {})

    lines: list[str] = []
    for name, prop in properties.items():
        field_type = json_schema_type_label(prop)
        desc = prop.get("description", "")
        line = f"- **`{name}`** ({field_type})"
        if desc:
            line += f": {desc}"
        lines.append(line)
    return "\n".join(lines)
