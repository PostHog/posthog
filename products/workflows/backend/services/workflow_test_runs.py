"""The activity log record of a workflow test step that sends real requests.

A test with `mock_async_functions` off runs one step with real side effects and the credentials of the
integrations its inputs name. The record keeps who ran which step with which integrations and where its
requests went, and never an input value: values can hold secrets.
"""

from collections.abc import Iterable
from typing import Any, Optional
from uuid import UUID

import requests

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, ActivityLog, Detail, log_activity

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.services.destination_test_runs import (
    integration_ids_in_value,
    record_test_run_request_origins,
)
from products.workflows.backend.facade.contracts import WorkflowActor

_INTEGRATION_INPUT_TYPES = ("integration", "integration_multi")
_EMAIL_INPUT_TYPES = ("native_email", "email")


# `ActivityDetailEncoder` serializes a context through `__dict__`, which a slotted class leaves empty.
@frozen(slots=False)
class WorkflowTestRunContext(ActivityContextBase):
    action_id: Optional[str]
    action_type: Optional[str]
    template_id: Optional[str]
    input_keys: list[str]
    integration_ids: list[int]
    request_origins: Optional[list[str]] = None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _email_sender_ids(value: Any) -> Iterable[int]:
    # The email service picks one sender from `integrationIds` when the list is set, else uses `integrationId`.
    sender = _as_dict(_as_dict(value).get("from"))
    many = sender.get("integrationIds")
    return integration_ids_in_value(many if isinstance(many, list) and many else sender.get("integrationId"))


def _integration_ids(template_id: Optional[str], config: dict[str, Any]) -> list[int]:
    # A function step takes its inputs schema from its template, as the worker does when it loads the step.
    template = HogFunctionTemplate.get_template(template_id) if template_id else None
    schemas: list[Any] = list((template.inputs_schema if template else None) or [])
    inputs = dict(_as_dict(config.get("inputs")))
    # The worker merges each mapping's inputs over the step inputs before it loads integrations.
    mappings = config.get("mappings")
    for mapping in mappings if isinstance(mappings, list) else []:
        mapping_schema = _as_dict(mapping).get("inputs_schema")
        schemas.extend(mapping_schema if isinstance(mapping_schema, list) else [])
        inputs.update(_as_dict(_as_dict(mapping).get("inputs")))
    ids: set[int] = set()
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        value = _as_dict(inputs.get(str(schema.get("key")))).get("value")
        if schema.get("type") in _INTEGRATION_INPUT_TYPES:
            ids.update(integration_ids_in_value(value))
        elif schema.get("type") in _EMAIL_INPUT_TYPES:
            ids.update(_email_sender_ids(value))
    return sorted(ids)


def _tested_action(actions: Any, current_action_id: Optional[str]) -> dict[str, Any]:
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        if action.get("id") == current_action_id if current_action_id else action.get("type") == "trigger":
            return action
    return {"id": current_action_id}


def workflow_test_run_context(
    actions: Any, current_action_id: Optional[str], encrypted_inputs: Any = None
) -> WorkflowTestRunContext:
    action = _tested_action(actions, current_action_id)
    config = _as_dict(action.get("config"))
    inputs = _as_dict(config.get("inputs"))
    # A saved flow keeps its secret inputs apart from `actions`, and the worker folds them back in.
    secret_keys = _as_dict(_as_dict(encrypted_inputs).get(str(action.get("id")))).keys()
    template_id = config.get("template_id") if isinstance(config.get("template_id"), str) else None
    return WorkflowTestRunContext(
        action_id=action.get("id"),
        action_type=action.get("type"),
        template_id=template_id,
        input_keys=sorted({*inputs.keys(), *secret_keys}),
        integration_ids=_integration_ids(template_id, config),
    )


def log_workflow_test_run(
    *,
    actor: WorkflowActor,
    workflow_id: Optional[UUID],
    name: Optional[str],
    actions: Any,
    current_action_id: Optional[str],
    encrypted_inputs: Any = None,
) -> Optional[ActivityLog]:
    # Without `strict`, production drops a failed write and the test still sends real requests.
    return log_activity(
        strict=True,
        organization_id=actor.organization_id,
        team_id=actor.team_id,
        user=actor.user,
        was_impersonated=actor.was_impersonated,
        item_id=str(workflow_id) if workflow_id else None,
        scope="HogFlow",
        activity="tested",
        detail=Detail(name=name, context=workflow_test_run_context(actions, current_action_id, encrypted_inputs)),
    )


def record_workflow_test_run_origins(
    row: Optional[ActivityLog], response: requests.Response, *, secret_inputs: Any = None
) -> None:
    record_test_run_request_origins(row, response, secret_inputs=secret_inputs)
