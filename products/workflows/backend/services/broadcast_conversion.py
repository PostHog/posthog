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
    paths = {(edge.get("from"), edge.get("to")) for edge in flow.edges or [] if isinstance(edge, dict)}
    return paths == {(trigger.get("id"), email.get("id")), (email.get("id"), exit_step.get("id"))}


def list_broadcast_conversion_candidates(
    *, team_id: int, user_access_control: Optional[UserAccessControl]
) -> list[WorkflowSummary]:
    """The team's workflows that could become broadcasts and that the caller may edit, newest first."""
    queryset = (
        annotate_broadcast_shape(
            HogFlow.objects.filter(
                team_id=team_id,
                origin_product__isnull=True,
                exit_condition=HogFlow.ExitCondition.ONLY_AT_END,
                draft__isnull=True,
            ).exclude(status=HogFlow.State.ARCHIVED)
        )
        .filter(_has_batch_trigger=True, _email_step_count=1, _has_other_step=False)
        .order_by("-updated_at")
    )
    candidates = [flow for flow in queryset if is_convertible_to_broadcast(flow)]
    if user_access_control is not None:
        # Converting needs editor access, so a workflow the caller can only view is not offered.
        user_access_control.preload_object_access_controls(cast("list[models.Model]", candidates))
        candidates = [
            flow
            for flow in candidates
            if user_access_control.check_access_level_for_object(flow, required_level="editor")
        ]
    return [WorkflowSummary(id=str(flow.id), name=flow.name or "", status=flow.status) for flow in candidates]


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
