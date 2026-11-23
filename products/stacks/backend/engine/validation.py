from __future__ import annotations

import re
import json
from collections.abc import Mapping
from graphlib import CycleError, TopologicalSorter
from math import isfinite
from typing import Any

from .expressions import BodyExpressions, definition_error
from .types import EngineError, Identity, Json, ResourceDescription, StackDescription

MAX_DESCRIPTION_BYTES = 5 * 1024 * 1024
MAX_DESCRIPTION_DEPTH = 32
MAX_RESOURCES = 2000


def _invalid_json() -> EngineError:
    return EngineError(
        [{"code": "invalid_definition", "message": "Use JSON values in this definition and run check again."}]
    )


def _too_large() -> EngineError:
    return EngineError(
        [
            {
                "code": "definition_too_large",
                "message": "Split the stack into smaller definitions and run check again. A stack can hold up to 5 MiB.",
            }
        ]
    )


def check_limits(description: StackDescription) -> None:
    if len(description["resources"]) > MAX_RESOURCES:
        raise EngineError(
            [
                {
                    "code": "too_many_definitions",
                    "message": f"Split the stack into groups of at most {MAX_RESOURCES} definitions.",
                }
            ]
        )
    remaining = MAX_DESCRIPTION_BYTES

    def visit(value: Any, depth: int, resource: Identity | None) -> None:
        nonlocal remaining
        if depth > MAX_DESCRIPTION_DEPTH:
            message = f"Reduce the nesting in this definition to {MAX_DESCRIPTION_DEPTH} levels and run check again."
            if resource is not None:
                raise definition_error(resource, "", message)
            raise EngineError([{"code": "invalid_definition", "message": message}])
        if (
            depth == 3
            and isinstance(value, dict)
            and isinstance(value.get("kind"), str)
            and isinstance(value.get("key"), str)
        ):
            resource = {"kind": value["kind"], "key": value["key"]}
        if isinstance(value, (dict, list)):
            remaining -= 2 + max(0, len(value) - 1)
            if remaining < 0:
                raise _too_large()
            if isinstance(value, dict):
                for key, child in value.items():
                    if not isinstance(key, str):
                        raise _invalid_json()
                    remaining -= 1
                    visit(key, depth, resource)
                    visit(child, depth + 1, resource)
            else:
                for child in value:
                    visit(child, depth + 1, resource)
        else:
            if isinstance(value, str):
                if len(value) > remaining:
                    raise _too_large()
                if not value.isascii():
                    try:
                        value.encode("utf-8")
                    except UnicodeEncodeError:
                        raise _invalid_json() from None
            elif value is not None and not (type(value) in (int, bool) or (type(value) is float and isfinite(value))):
                raise _invalid_json()
            try:
                remaining -= len(json.dumps(value, ensure_ascii=True))
            except ValueError:
                raise _invalid_json() from None
            if remaining < 0:
                raise _too_large()

    visit(description, 1, None)


def _secret_ref(value: Json) -> bool:
    return (
        isinstance(value, dict)
        and value.keys() == {"$secret"}
        and isinstance(value["$secret"], str)
        and bool(value["$secret"].strip())
    )


def _secret_required(resource: ResourceDescription, path: str) -> EngineError:
    return definition_error(
        resource, path, "Use a named stack secret for this field and run check again.", "secret_literal"
    )


def _destination_secrets(
    resource: ResourceDescription, group: dict[str, Json], prefix: str, rule: dict[str, Any], inherited: set[str]
) -> set[str]:
    sensitive_name = re.compile(rule["name_pattern"], re.IGNORECASE)
    inputs = group.get(rule["inputs"], {})
    schema = group.get(rule["schema"], [])
    if schema is None:
        schema = []
    if inputs is None:
        inputs = {}
    if not isinstance(schema, list) or not isinstance(inputs, dict):
        raise definition_error(
            resource, prefix + rule["inputs"], "Describe each input by name and list its input fields."
        )

    def check_nested(value: Json, path: str) -> None:
        if isinstance(value, dict):
            if _secret_ref(value) or "$ref" in value:
                return
            for name, child in value.items():
                child_path = f"{path}.{name}"
                if sensitive_name.search(name):
                    if not _secret_ref(child):
                        raise _secret_required(resource, child_path)
                else:
                    check_nested(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check_nested(child, f"{path}[{index}]")

    marked = inherited.copy()
    for index, field in enumerate(schema):
        path = f"{prefix}{rule['schema']}[{index}]"
        if (
            not isinstance(field, dict)
            or not isinstance(field.get("key"), str)
            or not isinstance(field.get("secret", False), bool)
        ):
            raise definition_error(resource, path, "Give this input a name and mark it as secret or public.")
        key = str(field["key"])
        if field.get("secret") or sensitive_name.search(key):
            marked.add(key)
    for index, field in enumerate(schema):
        if not isinstance(field, dict) or "default" not in field:
            continue
        path = f"{prefix}{rule['schema']}[{index}].default"
        if field["key"] in marked and not _secret_ref(field["default"]):
            raise _secret_required(resource, path)
        check_nested(field["default"], path)
    for key, entry in inputs.items():
        path = f"{prefix}{rule['inputs']}.{key}"
        entry_marked = isinstance(entry, dict) and entry.get("secret") is True
        if key in marked or sensitive_name.search(key) or entry_marked:
            if _secret_ref(entry):
                continue
            if not (
                isinstance(entry, dict)
                and entry.keys() <= {"value", "templating", "secret"}
                and isinstance(entry.get("secret", False), bool)
                and _secret_ref(entry.get("value"))
                and ("templating" not in entry or entry["templating"] in ("hog", "liquid"))
            ):
                raise _secret_required(resource, path)
        else:
            if isinstance(entry, dict) and entry.get("secret") is False:
                entry = {k: v for k, v in entry.items() if k != "secret"}
            check_nested(entry, path)
    return marked


def check_secret_positions(resource: ResourceDescription, mapping: dict[str, Any]) -> None:
    rule = mapping.get("secret_inputs")
    if not rule:
        return
    body = resource["body"]
    if "connection" in rule:
        _connection_secrets(resource, rule, mapping["public_inputs"])
        return
    templates: dict[str, list[str]] = rule["template_inputs"]
    template = body.get("template_id")
    if isinstance(template, dict):
        # A reference can select any template during a push.
        template_fields = {field for fields in templates.values() for field in fields}
    else:
        template_fields = set(templates.get(template, ())) if isinstance(template, str) else set()
    marked = _destination_secrets(resource, body, "", rule, template_fields)
    nested = body.get(rule["groups"], [])
    if nested is not None:
        if not isinstance(nested, list):
            raise definition_error(resource, rule["groups"], "List each destination mapping in this definition.")
        for index, group in enumerate(nested):
            if not isinstance(group, dict):
                raise definition_error(resource, rule["groups"], "Give each destination mapping an object body.")
            _destination_secrets(resource, group, f"{rule['groups']}[{index}].", rule, marked)


def _connection_secrets(resource: ResourceDescription, rule: dict[str, Any], public_inputs: list[str]) -> None:
    body = resource["body"]
    payload = body.get(rule["connection"])
    if not isinstance(payload, dict):
        return
    public: dict[tuple[str | int, ...], list[Json] | None] = {(key,): None for key in public_inputs}
    source_type = body.get("source_type")
    if isinstance(source_type, str):
        public.update(
            (tuple(path.split(".")), choices) for path, choices in rule["public_paths"].get(source_type, {}).items()
        )

    def visit(value: Json, parts: tuple[str | int, ...], path: str) -> None:
        if _secret_ref(value):
            return
        if parts in public:
            if isinstance(value, dict) and value.keys() == {"$ref"}:
                return
            if isinstance(value, (str, int, float, bool)):
                choices = public[parts]
                if choices is not None and not any(
                    type(value) is type(choice) and value == choice for choice in choices
                ):
                    raise definition_error(resource, path, "Choose a supported connection setting and run check again.")
                return
            raise _secret_required(resource, path)
        if isinstance(value, dict) and value and not ({"$secret", "$ref"} & value.keys()):
            for key, child in value.items():
                visit(child, (*parts, key), f"{path}.{key}")
        elif isinstance(value, list) and value:
            for index, child in enumerate(value):
                visit(child, (*parts, index), f"{path}[{index}]")
        else:
            raise _secret_required(resource, path)

    for name, value in payload.items():
        if name != "schemas":
            visit(value, (name,), f"{rule['connection']}.{name}")


def check_nested_fields(resource: ResourceDescription, mapping: dict[str, Any]) -> None:
    # Some mapped fields have structured children; arbitrary JSON fields such as queries keep their own schema.
    read_api = mapping["read_api"]
    for key, known in read_api.get("object_fields", {}).items():
        value = resource["body"].get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise definition_error(resource, key, "Give this field an object and run check again.")
        for field in sorted(value.keys() - set(known)):
            raise definition_error(resource, f"{key}.{field}", "Remove this unsupported field and run check again.")
    for key, known in read_api.get("list_fields", {}).items():
        if key not in resource["body"]:
            continue
        items = resource["body"][key]
        if not isinstance(items, list):
            raise definition_error(resource, key, "Give this field a list of objects and run check again.")
        allowed = set(known) | {
            path.removeprefix(key + "[].") for path in mapping.get("typed_only", ()) if path.startswith(key + "[].")
        }
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise definition_error(resource, f"{key}[{index}]", "Give this entry an object and run check again.")
            for field in sorted(item.keys() - allowed):
                raise definition_error(
                    resource, f"{key}[{index}].{field}", "Remove this unsupported field and run check again."
                )


def check_references(resource: ResourceDescription, expr: BodyExpressions) -> None:
    def visit(value: Json, path: str) -> None:
        if isinstance(value, dict):
            if "$ref" in value or "$secret" in value:
                expr.reference(value, path)
            else:
                for key, child in value.items():
                    visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    for key, value in resource["body"].items():
        visit(value, key)


def declared_dependencies(resource: ResourceDescription, definitions: set[tuple[str, str]]) -> set[tuple[str, str]]:
    explicit = resource.get("depends_on", [])
    message = "List definitions in this stack by kind and key in depends_on."
    if not isinstance(explicit, list):
        raise definition_error(resource, "depends_on", message)
    dependencies = set()
    for index, dependency in enumerate(explicit):
        if (
            not isinstance(dependency, dict)
            or dependency.keys() != {"kind", "key"}
            or not isinstance(kind := dependency.get("kind"), str)
            or not isinstance(key := dependency.get("key"), str)
            or (kind, key) not in definitions
        ):
            raise definition_error(resource, f"depends_on[{index}]", message)
        dependencies.add((kind, key))
    return dependencies


def check_cycles(graph: Mapping[tuple[str, str], set[tuple[str, str]]]) -> None:
    try:
        TopologicalSorter(graph).prepare()
    except CycleError as cycle:
        kind, key = cycle.args[1][0]
        raise definition_error(
            {"kind": kind, "key": key},
            "",
            "Break the loop between these definitions and run check again.",
            "reference_cycle",
        ) from None
