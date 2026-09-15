"""The output fields a workflow step asks its AI task for, and the schema they become."""

import re
from collections.abc import Mapping
from typing import Any

from posthog.cdp.workflow_step_resume import RESULT_BYTE_CAP, RESULT_STRING_CAP

OUTPUT_FIELD_TYPES = ("string", "number", "boolean")
MAX_OUTPUT_FIELDS = 20
_OUTPUT_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Keys the tasks product writes into `TaskRun.output` next to the agent's fields.
RUN_OUTPUT_RESERVED_KEYS = frozenset(
    {"final_message", "pr_url", "pr_urls", "head_branches", "pr_state", "pr_merged", "ci_status", "commit_push"}
)


class WorkflowTaskOutputFieldsInvalid(ValueError):
    pass


def build_output_schema(fields: Mapping[str, str]) -> dict[str, Any]:
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
        properties[name] = {"type": field_type}
        if field_type == "string":
            properties[name]["maxLength"] = RESULT_STRING_CAP
    return {"type": "object", "properties": properties, "required": list(properties)}


def output_fields_sentence(output_schema: Mapping[str, Any] | None) -> str | None:
    """Tells the agent which fields the step reads and the budget they share with the message."""
    properties = (output_schema or {}).get("properties") or {}
    if not properties:
        return None
    listed = ", ".join(f"{name} ({spec.get('type', 'any')})" for name, spec in properties.items())
    return (
        f"The workflow reads these fields from your structured output before it reads your final "
        f"message: {listed}. Keep each text field within {RESULT_STRING_CAP} characters. The fields "
        f"and the message share a {RESULT_BYTE_CAP} byte budget, and the fields take priority."
    )
