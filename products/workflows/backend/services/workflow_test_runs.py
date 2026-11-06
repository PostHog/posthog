"""The activity log record of a workflow test step that sends real requests.

A test with `mock_async_functions` off runs one step with real side effects and the credentials of the
integrations its inputs name. The record keeps who ran which step with which integrations, and never an
input value: values can hold secrets.
"""

from collections.abc import Iterable
from typing import Any, Optional
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.contracts import WorkflowActor

_INTEGRATION_INPUT_TYPES = ("integration", "integration_multi")


# `ActivityDetailEncoder` serializes a context through `__dict__`, which a slotted class leaves empty.
@frozen(slots=False)
class WorkflowTestRunContext(ActivityContextBase):
    action_id: Optional[str]
    action_type: Optional[str]
    template_id: Optional[str]
    input_keys: list[str]
    integration_ids: list[int]


def _integration_ids_in_value(value: Any) -> Iterable[int]:
    if isinstance(value, dict):
        value = value.get("integrationId")
    for candidate in value if isinstance(value, list) else [value]:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            yield candidate


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _integration_ids(template_id: Optional[str], inputs: dict[str, Any]) -> list[int]:
    # A function step takes its inputs schema from its template, as the worker does when it loads the step.
    template = HogFunctionTemplate.get_template(template_id) if template_id else None
    ids: set[int] = set()
    for schema in (template.inputs_schema if template else None) or []:
        if isinstance(schema, dict) and schema.get("type") in _INTEGRATION_INPUT_TYPES:
            entry = _as_dict(inputs.get(str(schema.get("key"))))
            ids.update(_integration_ids_in_value(entry.get("value")))
    return sorted(ids)


def _tested_action(actions: Any, current_action_id: Optional[str]) -> dict[str, Any]:
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        if action.get("id") == current_action_id if current_action_id else action.get("type") == "trigger":
            return action
    return {"id": current_action_id}


def workflow_test_run_context(actions: Any, current_action_id: Optional[str]) -> WorkflowTestRunContext:
    action = _tested_action(actions, current_action_id)
    config = _as_dict(action.get("config"))
    inputs = _as_dict(config.get("inputs"))
    template_id = config.get("template_id") if isinstance(config.get("template_id"), str) else None
    return WorkflowTestRunContext(
        action_id=action.get("id"),
        action_type=action.get("type"),
        template_id=template_id,
        input_keys=sorted(inputs.keys()),
        integration_ids=_integration_ids(template_id, inputs),
    )


def log_workflow_test_run(
    *,
    actor: WorkflowActor,
    workflow_id: Optional[UUID],
    name: Optional[str],
    actions: Any,
    current_action_id: Optional[str],
) -> None:
    # Without `strict`, production drops a failed write and the test still sends real requests.
    log_activity(
        strict=True,
        organization_id=actor.organization_id,
        team_id=actor.team_id,
        user=actor.user,
        was_impersonated=actor.was_impersonated,
        item_id=str(workflow_id) if workflow_id else None,
        scope="HogFlow",
        activity="tested",
        detail=Detail(name=name, context=workflow_test_run_context(actions, current_action_id)),
    )
