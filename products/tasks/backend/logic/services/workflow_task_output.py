"""The output fields a workflow step asks its AI task for, and the schema they become."""

import re
from collections.abc import Mapping
from typing import Any

from products.cdp.backend.workflow_step_resume import RESULT_BYTE_CAP, RESULT_STRING_CAP

OUTPUT_FIELD_TYPES = ("string", "number", "boolean", "json")
MAX_OUTPUT_FIELDS = 20
MAX_FIELD_DESCRIPTION = 500
_OUTPUT_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Keys the tasks product writes into `TaskRun.output` next to the agent's fields.
RUN_OUTPUT_RESERVED_KEYS = frozenset(
    {"final_message", "pr_url", "pr_urls", "head_branches", "pr_state", "pr_merged", "ci_status", "commit_push"}
)


class WorkflowTaskOutputFieldsInvalid(ValueError):
    pass


def build_output_schema(fields: Mapping[str, str], descriptions: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The JSON Schema the agent runtime enforces for the step's output fields.

    Built here from a flat name-to-type map so no caller hands the validator a schema of its
    own. Strings carry the step's per-string cap so the agent sees the limit up front.
    """
    if not fields:
        raise WorkflowTaskOutputFieldsInvalid("output_fields must name at least one field")
    if len(fields) > MAX_OUTPUT_FIELDS:
        raise WorkflowTaskOutputFieldsInvalid(f"output_fields allows at most {MAX_OUTPUT_FIELDS} fields")
    properties: dict[str, dict[str, Any]] = {}
    for name, field_type in fields.items():
        if not _OUTPUT_FIELD_NAME.match(name):
            raise WorkflowTaskOutputFieldsInvalid(
                f"output field {name!r} must be a name of letters, digits and underscores, not starting with a digit"
            )
        if name in RUN_OUTPUT_RESERVED_KEYS:
            raise WorkflowTaskOutputFieldsInvalid(f"output field {name!r} is reserved by the task result")
        if field_type not in OUTPUT_FIELD_TYPES:
            raise WorkflowTaskOutputFieldsInvalid(
                f"output field {name!r} has type {field_type!r}; expected one of {', '.join(OUTPUT_FIELD_TYPES)}"
            )
        # A JSON field takes any object or list; the agent reads its description for the shape.
        # `additionalProperties` keeps adapters with strict schemas from forbidding every key.
        properties[name] = (
            {"type": ["object", "array"], "additionalProperties": True}
            if field_type == "json"
            else {"type": field_type}
        )
        if description := (descriptions or {}).get(name):
            properties[name]["description"] = description[:MAX_FIELD_DESCRIPTION]
        if field_type == "string":
            properties[name]["maxLength"] = RESULT_STRING_CAP
    return {"type": "object", "properties": properties, "required": list(properties)}


def _describe_field(name: str, spec: Mapping[str, Any]) -> str:
    field_type = spec.get("type", "any")
    label = f"{name} ({'json' if isinstance(field_type, list) else field_type})"
    return f"{label}: {spec['description']}" if spec.get("description") else label


def output_fields_sentence(output_schema: Mapping[str, Any] | None) -> str | None:
    """Tells the agent which fields the step reads and the budget they share with the message."""
    properties = (output_schema or {}).get("properties") or {}
    if not properties:
        return None
    listed = "; ".join(_describe_field(name, spec) for name, spec in properties.items())
    return (
        f"The workflow reads these fields from your structured output before it reads your final "
        f"message: {listed}. Keep each text field within {RESULT_STRING_CAP} characters. The fields "
        f"and the message share a {RESULT_BYTE_CAP} byte budget, and the fields take priority."
    )
