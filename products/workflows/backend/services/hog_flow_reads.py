"""Reading one workflow for the API: the reader's object access check, then the workflow as a contract
with its secret inputs masked."""

from typing import TYPE_CHECKING, Optional, cast
from uuid import UUID

from django.core.exceptions import ValidationError

from products.workflows.backend.facade.contracts import Workflow, WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.hog_flow_schedules import list_schedules_oldest_first
from products.workflows.backend.services.hog_flow_secrets import TemplateCache, mask_workflow_fields

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl


def get_workflow(
    *,
    team_id: int,
    workflow_id: UUID | str,
    user_access_control: "UserAccessControl | None",
    required_level: str | None,
) -> Workflow:
    """The team's workflow, or WorkflowNotFound, or WorkflowAccessDenied when the reader's level for
    it is below `required_level`. Pass None for both access arguments to skip the check, as a
    service credential does."""
    try:
        flow = HogFlow.objects.select_related("created_by").get(team_id=team_id, pk=workflow_id)
    except (HogFlow.DoesNotExist, ValidationError, ValueError):
        # ValidationError and ValueError fire when the id is not a parseable UUID.
        raise WorkflowNotFound()
    # The same check AccessControlPermission.has_object_permission runs on a model viewset's object.
    if (
        user_access_control is not None
        and required_level is not None
        and not user_access_control.check_access_level_for_object(
            flow, required_level=cast("AccessControlLevel", required_level)
        )
    ):
        raise WorkflowAccessDenied(required_level)
    return _to_workflow(flow, user_access_control, template_cache={})


def _to_workflow(
    flow: HogFlow, user_access_control: "UserAccessControl | None", template_cache: TemplateCache
) -> Workflow:
    masked: dict[str, object] = {"actions": flow.actions, "trigger": flow.trigger, "draft": flow.draft}
    mask_workflow_fields(
        masked,
        live_actions=flow.actions,
        live_trigger=flow.trigger,
        encrypted_inputs=flow.encrypted_inputs,
        draft_encrypted_inputs=flow.draft_encrypted_inputs,
        template_cache=template_cache,
    )
    access_level: Optional[str] = (
        user_access_control.get_user_access_level(flow) if user_access_control is not None else None
    )
    return Workflow(
        id=flow.id,
        team_id=flow.team_id,
        name=flow.name,
        description=flow.description,
        version=flow.version,
        status=flow.status,
        origin_product=flow.origin_product,
        created_at=flow.created_at,
        created_by=flow.created_by,
        updated_at=flow.updated_at,
        trigger=masked["trigger"],
        trigger_masking=flow.trigger_masking,
        conversion=flow.conversion,
        exit_condition=flow.exit_condition,
        email_sending_rate_limit=flow.email_sending_rate_limit,
        edges=flow.edges,
        actions=cast("list[dict] | dict", masked["actions"]),
        abort_action=flow.abort_action,
        variables=flow.variables,
        billable_action_types=flow.billable_action_types,
        schedules=tuple(list_schedules_oldest_first(team_id=flow.team_id, hog_flow_id=flow.id)),
        draft=cast("dict | None", masked["draft"]),
        draft_updated_at=flow.draft_updated_at,
        action_redirects=flow.action_redirects,
        email_sending_paused_at=flow.email_sending_paused_at,
        email_sending_paused_reason=flow.email_sending_paused_reason,
        email_sending_paused_by=flow.email_sending_paused_by,
        email_sending_resumed_at=flow.email_sending_resumed_at,
        user_access_level=access_level,
    )
