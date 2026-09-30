import json
import difflib
from copy import deepcopy
from functools import cache
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from products.workflows.backend.facade.contracts import WorkflowCodeErrorStatus
from products.workflows.backend.services.workflow_code.document import WorkflowDocument, shown
from products.workflows.backend.services.workflow_code.errors import (
    DocumentError,
    DocumentInvalid,
    DocumentPath,
    PointsAt,
    describe_path,
)

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def workflow_document_schema() -> dict[str, Any]:
    return deepcopy(_served_schema())


@cache
def _served_schema() -> dict[str, Any]:
    schema = _dispatch_unions_on_type(WorkflowDocument.model_json_schema(by_alias=True))
    return {"$schema": JSON_SCHEMA_DIALECT, **schema}


def _dispatch_unions_on_type(node: Any) -> Any:
    """Rewrite each tagged union from oneOf into if/then on `type`.

    A plain JSON Schema validator ignores the OpenAPI `discriminator` Pydantic emits, so under oneOf
    one wrong step fails every member and the validator reports only that the step matches none of
    them. With if/then it checks the step against its own kind and reports the field that is wrong.
    """
    if isinstance(node, list):
        return [_dispatch_unions_on_type(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "oneOf" in node and "discriminator" in node:
        return _if_then_union(
            node["discriminator"]["mapping"], {k: v for k, v in node.items() if k not in ("oneOf", "discriminator")}
        )
    return {key: _dispatch_unions_on_type(value) for key, value in node.items()}


def _if_then_union(mapping: dict[str, str], annotations: dict[str, Any]) -> dict[str, Any]:
    tags_by_ref: dict[str, list[str]] = {}
    for tag, ref in mapping.items():
        tags_by_ref.setdefault(ref, []).append(tag)
    return {
        **annotations,
        "type": "object",
        "required": ["type"],
        "properties": {"type": {"enum": list(mapping)}},
        "allOf": [
            {
                "if": {"properties": {"type": {"enum": tags}}, "required": ["type"]},
                "then": {"$ref": ref},
            }
            for ref, tags in tags_by_ref.items()
        ],
    }


def _object_schema_at(path: DocumentPath, data: Any) -> dict[str, Any] | None:
    """The served schema of the object at `path`, following each union to the member `data` selects."""
    schema = _served_schema()
    node = _select(schema, data, schema)
    for part in path:
        data = data[part] if _has(data, part) else None
        if node is None:
            return None
        if isinstance(part, int):
            node = _select(node.get("items"), data, schema)
        else:
            node = _select((node.get("properties") or {}).get(part), data, schema)
    return node


def _has(data: Any, part: str | int) -> bool:
    if isinstance(part, int):
        return isinstance(data, list) and 0 <= part < len(data)
    return isinstance(data, dict) and part in data


def _select(node: Any, data: Any, root: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    if "$ref" in node:
        return _select(root["$defs"][node["$ref"].rsplit("/", 1)[-1]], data, root)
    if "allOf" in node and isinstance(data, dict):
        for branch in node["allOf"]:
            if data.get("type") in branch.get("if", {}).get("properties", {}).get("type", {}).get("enum", []):
                return _select(branch["then"], data, root)
    for member in node.get("anyOf", []):
        selected = _select(member, data, root)
        if selected is not None and selected.get("type") in ("object", "array"):
            return selected
    return node


def validate_document(data: Any, scalar_sources: dict[DocumentPath, str]) -> WorkflowDocument:
    try:
        return WorkflowDocument.model_validate(data)
    except ValidationError as error:
        errors: dict[tuple[WorkflowCodeErrorStatus, DocumentPath], DocumentError] = {}
        for detail in error.errors():
            document_error = _describe(detail, data, scalar_sources)
            errors.setdefault((document_error.status, document_error.path or ()), document_error)
        raise DocumentInvalid(_without_missing_fields_misspelled_nearby(list(errors.values()), data))


def _without_missing_fields_misspelled_nearby(errors: list[DocumentError], data: Any) -> list[DocumentError]:
    """Drop a missing field when a misspelling of it is also reported, as one mistake gives one error."""
    misspelled = {
        (*error.path[:-1], closest)
        for error in errors
        if error.status == WorkflowCodeErrorStatus.UNKNOWN_FIELD
        and error.path
        and (closest := _closest_field(error.path, data)) is not None
    }
    return [
        error
        for error in errors
        if not (error.status == WorkflowCodeErrorStatus.MISSING_FIELD and error.path in misspelled)
    ]


def _describe(detail: ErrorDetails, data: Any, scalar_sources: dict[DocumentPath, str]) -> DocumentError:
    path = _document_path(detail["loc"], data)
    kind = detail["type"]
    context = detail.get("ctx") or {}
    if kind == "document_error":
        return DocumentError(
            status=WorkflowCodeErrorStatus.INVALID_VALUE,
            message=f"{describe_path(path)}: {context['message']}",
            why=context["why"],
            fix=context["fix"],
            path=path,
        )
    if kind == "missing":
        return _missing_field(path, data)
    if kind == "extra_forbidden":
        return _unknown_field(path, data)
    if kind == "union_tag_invalid":
        return _unknown_type(path, context)
    if kind == "union_tag_not_found":
        return _missing_field((*path, "type"), data)
    if path == ("version",):
        return DocumentError(
            status=WorkflowCodeErrorStatus.UNSUPPORTED_VERSION,
            message=f"version is {scalar_sources.get(path, repr(detail['input']))}, and PostHog reads version 1.",
            why="The version says which shape the file has, and 1 is the only version so far.",
            fix="Set version: 1, written as a number without quotes.",
            path=path,
        )
    if kind == "string_type" and (detail["input"] is None or isinstance(detail["input"], (bool, int, float))):
        return _not_text(path, detail["input"], scalar_sources.get(path))
    if path == ():
        return DocumentError(
            status=WorkflowCodeErrorStatus.INVALID_VALUE,
            message="The file holds no workflow.",
            why="A workflow file is a mapping with version, key, name, trigger and steps at the top.",
            fix="Start the file with version: 1, then add key, name, trigger and steps.",
            path=None,
        )
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_VALUE,
        message=f"{describe_path(path)}: {detail['msg']}.",
        why=_field_description(path, data) or "The schema says what each field takes.",
        fix="Change the value to what the schema describes for this field. The code_schema endpoint returns the schema.",
        path=path,
    )


def _document_path(loc: tuple[str | int, ...], data: Any) -> DocumentPath:
    """Turn a Pydantic location into the document's own path.

    Pydantic puts the union tag after each union position, as in steps.0.delay.duration. The file has
    no such level, so the tag is dropped wherever the value at that position carries it as its type.
    """
    path: DocumentPath = ()
    node = data
    tag_dropped = False
    for part in loc:
        if not tag_dropped and _is_union_position(path) and isinstance(node, dict) and part == node.get("type"):
            tag_dropped = True
            continue
        tag_dropped = False
        path = (*path, part)
        node = node[part] if _has(node, part) else None
    return path


def _is_union_position(path: DocumentPath) -> bool:
    if path == ("trigger",):
        return True
    if len(path) >= 2 and isinstance(path[-1], int) and path[-2] in ("steps", "then"):
        return True
    return len(path) >= 3 and isinstance(path[-1], int) and isinstance(path[-2], int) and path[-3] == "branches"


def _field_description(path: DocumentPath, data: Any) -> str | None:
    if not path:
        return None
    parent = _object_schema_at(path[:-1], data) or {}
    field = (parent.get("properties") or {}).get(path[-1])
    if not isinstance(field, dict):
        return None
    return field.get("description")


def _missing_field(path: DocumentPath, data: Any) -> DocumentError:
    field = path[-1]
    parent = describe_path(path[:-1])
    description = _field_description(path, data)
    return DocumentError(
        status=WorkflowCodeErrorStatus.MISSING_FIELD,
        message=f"{parent} has no {field}.",
        why=f"{field} is required. {description}" if description else f"{field} is required.",
        fix=f"Add {field} to {parent if path[:-1] else 'the top of the file'}.",
        path=path,
        points_at=PointsAt.PARENT,
    )


def _known_fields(parent_path: DocumentPath, data: Any) -> list[str]:
    parent = _object_schema_at(parent_path, data) or {}
    return list((parent.get("properties") or {}).keys())


def _closest_field(path: DocumentPath, data: Any) -> str | None:
    close = difflib.get_close_matches(str(path[-1]), _known_fields(path[:-1], data), n=1)
    return close[0] if close else None


def _unknown_field(path: DocumentPath, data: Any) -> DocumentError:
    field = str(path[-1])
    closest = _closest_field(path, data)
    if closest is not None:
        fix = f"Rename {field} to {closest}."
    else:
        fix = f"Remove {field}. The fields here are {', '.join(_known_fields(path[:-1], data))}."
    return DocumentError(
        status=WorkflowCodeErrorStatus.UNKNOWN_FIELD,
        message=f"{describe_path(path)} is not a field PostHog knows here.",
        why="The schema lists every field a workflow file can use. PostHog refuses any other field, so a typo does not go unnoticed.",
        fix=fix,
        path=path,
        points_at=PointsAt.KEY,
    )


def _unknown_type(path: DocumentPath, context: dict[str, Any]) -> DocumentError:
    kind = "trigger" if path == ("trigger",) else "step"
    fix = f"Use one of {context.get('expected_tags')}."
    if kind == "step":
        fix += " For any other action, use type: step and set its action_type."
    return DocumentError(
        status=WorkflowCodeErrorStatus.UNKNOWN_TYPE,
        message=f"{describe_path((*path, 'type'))} is {shown(str(context.get('tag')))}, which is not a {kind} type.",
        why=f"The type decides which fields a {kind} has, so PostHog reads it first.",
        fix=fix,
        path=(*path, "type"),
    )


def _not_text(path: DocumentPath, value: bool | int | float | None, source: str | None) -> DocumentError:
    if isinstance(value, bool):
        reading = "true or false"
    elif value is None:
        reading = "empty"
    else:
        reading = "a number"
    if source is None:
        return DocumentError(
            status=WorkflowCodeErrorStatus.INVALID_VALUE,
            message=f"{describe_path(path)} is {json.dumps(value)}, which is {reading}, and this field takes text.",
            why="PostHog does not turn other types into text, because the value can change on the way: 1.10 becomes 1.1.",
            fix="Write the value as a JSON string, in double quotes, exactly as it should read.",
            path=path,
        )
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_VALUE,
        message=f"{describe_path(path)} is {shown(source)}, which YAML reads as {reading}, and this field takes text.",
        why="YAML reads unquoted numbers, true, false and null as other types. PostHog does not turn them back into text, because the value can change on the way: 1.10 becomes 1.1.",
        fix=f"Put the value in quotes: {shown(source)}.",
        path=path,
    )
