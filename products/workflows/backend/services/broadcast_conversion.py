"""Moving a workflow that only sends one email to a batch audience over to the broadcasts product."""

from typing import Final, Optional, cast
from uuid import UUID

from django.db import models, transaction
from django.utils import timezone

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.contracts import WorkflowActor, WorkflowSummary
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.hog_flow_activity import log_workflow_activity
from products.workflows.backend.services.hog_flow_reads import BROADCAST_TRIGGER_TYPE, annotate_broadcast_shape
from products.workflows.backend.services.hog_flow_writes import field_values

BROADCAST_CONVERSION_CANDIDATE_LIMIT: Final = 100


def is_convertible_to_broadcast(flow: HogFlow) -> bool:
    """Whether the broadcast editor can own this workflow without losing anything it holds.

    Mirrors canEditInWizard in the frontend: one trigger, one email and one exit, joined trigger to email
    to exit, for a person audience. The editor always saves `exit_only_at_end` and edits the live graph,
    so another exit condition or a staged draft would be dropped on its next save."""
    if flow.origin_product is not None or flow.status == HogFlow.State.ARCHIVED:
        return False
    if flow.exit_condition != HogFlow.ExitCondition.ONLY_AT_END or flow.draft is not None:
        return False
    actions = [action for action in flow.actions or [] if isinstance(action, dict)]
    steps = {
        step_type: [action for action in actions if action.get("type") == step_type]
        for step_type in ("trigger", "function_email", "exit")
    }
    if len(actions) != 3 or any(len(found) != 1 for found in steps.values()):
        return False
    trigger, email, exit_step = steps["trigger"][0], steps["function_email"][0], steps["exit"][0]
    config = trigger.get("config") or {}
    if config.get("type") != BROADCAST_TRIGGER_TYPE or (config.get("filters") or {}).get("audience_type") == "accounts":
        return False
    return _joins_in_order(flow, trigger.get("id"), email.get("id"), exit_step.get("id"))


def _joins_in_order(flow: HogFlow, trigger_id: object, email_id: object, exit_id: object) -> bool:
    """Whether the only edges run trigger to email and email to exit."""
    paths = {(edge.get("from"), edge.get("to")) for edge in flow.edges or [] if isinstance(edge, dict)}
    return paths == {(trigger_id, email_id), (email_id, exit_id)}


def _json_path(path: str) -> models.Func:
    return models.Func(models.Value(path), template="%(expressions)s::jsonpath", output_field=models.TextField())


def _step_count(step_type: str) -> models.Func:
    steps = models.Func(
        models.F("actions"),
        _json_path(f'$[*] ? (@.type == "{step_type}")'),
        function="jsonb_path_query_array",
        output_field=models.JSONField(),
    )
    return models.Func(steps, function="jsonb_array_length", output_field=models.IntegerField())


def _step_id(step_type: str) -> models.Func:
    return models.Func(
        models.F("actions"),
        _json_path(f'$[*] ? (@.type == "{step_type}").id'),
        function="jsonb_path_query_first",
        output_field=models.JSONField(),
    )


def list_broadcast_conversion_candidates(
    *, team_id: int, user_access_control: Optional[UserAccessControl], limit: int
) -> list[WorkflowSummary]:
    """Up to `limit` of the team's workflows that could become broadcasts and that the caller may edit,
    newest first. The shape checks run in Postgres, so only small columns load and never every row."""
    queryset = (
        annotate_broadcast_shape(
            HogFlow.objects.filter(
                team_id=team_id,
                origin_product__isnull=True,
                exit_condition=HogFlow.ExitCondition.ONLY_AT_END,
                draft__isnull=True,
            ).exclude(status=HogFlow.State.ARCHIVED)
        )
        .annotate(
            _step_count=models.Func(
                models.F("actions"), function="jsonb_array_length", output_field=models.IntegerField()
            ),
            _trigger_count=_step_count("trigger"),
            _exit_count=_step_count("exit"),
            _trigger_id=_step_id("trigger"),
            _email_id=_step_id("function_email"),
            _exit_id=_step_id("exit"),
            _account_audience=models.Func(
                models.F("actions"),
                _json_path('$[*] ? (@.type == "trigger" && @.config.filters.audience_type == "accounts")'),
                function="jsonb_path_exists",
                output_field=models.BooleanField(),
            ),
        )
        .filter(
            _has_batch_trigger=True,
            _email_step_count=1,
            _has_other_step=False,
            _step_count=3,
            _trigger_count=1,
            _exit_count=1,
            _account_audience=False,
        )
        .only("id", "team_id", "name", "status", "edges", "created_by")
        .order_by("-updated_at", "id")
    )
    found: list[HogFlow] = []
    offset = 0
    while len(found) < limit:
        page = list(queryset[offset : offset + limit])
        if not page:
            break
        offset += len(page)
        page = [flow for flow in page if _joins_in_order(flow, flow._trigger_id, flow._email_id, flow._exit_id)]
        if user_access_control is not None:
            # Converting needs editor access, so a workflow the caller can only view is not offered.
            user_access_control.preload_object_access_controls(cast("list[models.Model]", page))
            page = [
                flow
                for flow in page
                if user_access_control.check_access_level_for_object(flow, required_level="editor")
            ]
        found.extend(page)
    return [WorkflowSummary(id=str(flow.id), name=flow.name or "", status=flow.status) for flow in found[:limit]]


def convert_workflow_to_broadcast(*, team_id: int, hog_flow_id: UUID, actor: WorkflowActor) -> bool:
    """Hand the workflow to the broadcasts product and log it. Returns False when it cannot become one."""
    with transaction.atomic():
        flow = HogFlow.objects.select_for_update().filter(team_id=team_id, pk=hog_flow_id).first()
        if flow is None or not is_convertible_to_broadcast(flow):
            return False
        before = field_values(flow)
        flow.origin_product = HogFlow.OriginProduct.BROADCASTS
        flow.updated_at = timezone.now()
        # A queryset update skips the worker reload that save() sends, since the owner does not change how
        # the workflow runs.
        HogFlow.objects.filter(team_id=team_id, pk=hog_flow_id).update(
            origin_product=flow.origin_product, updated_at=flow.updated_at
        )
    log_workflow_activity(
        actor=actor,
        workflow_id=hog_flow_id,
        name=flow.name,
        activity="converted_to_broadcast",
        previous=before,
        current=field_values(flow),
    )
    return True
