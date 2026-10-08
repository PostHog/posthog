"""The activity log for workflow changes: one entry per change, with a field diff when the caller has
the workflow's fields from before and after the write."""

from collections.abc import Mapping
from datetime import datetime
from typing import Final, Optional, cast
from uuid import UUID

from django.db import models, transaction

from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.contracts import WorkflowActor
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.hog_flow_writes import field_values
from products.workflows.backend.services.workflow_email_health import resume_email_sending

_SCOPE: Final = "HogFlow"


def log_workflow_activity(
    *,
    actor: WorkflowActor,
    workflow_id: UUID,
    name: Optional[str],
    activity: str,
    previous: Optional[Mapping[str, object]] = None,
    current: Optional[Mapping[str, object]] = None,
    detail_type: Optional[str] = None,
) -> None:
    """Log one change to a workflow. Pass the field values from before and after the write to record
    which fields changed."""
    try:
        changes = (
            changes_between(
                _SCOPE,
                previous=HogFlow(**previous),
                current=HogFlow(**current) if current is not None else None,
            )
            if previous is not None
            else None
        )
        log_activity(
            organization_id=actor.organization_id,
            team_id=actor.team_id,
            user=actor.user,
            was_impersonated=actor.was_impersonated,
            item_id=str(workflow_id),
            scope=_SCOPE,
            activity=activity,
            detail=Detail(name=name or _SCOPE, type=detail_type, changes=changes),
        )
    except Exception:
        # A failed audit write must not fail the change it describes.
        pass


def resume_workflow_email_sending(*, team_id: int, hog_flow_id: UUID, actor: WorkflowActor) -> datetime | None:
    """Resume a paused workflow's email as a customer and log it. Returns the resume time, or None when
    sending was not paused. Raises StaffPausedError when only staff may resume."""
    before = HogFlow.objects.get(team_id=team_id, pk=hog_flow_id)
    resumed_at = resume_email_sending(team_id=team_id, hog_flow_id=hog_flow_id)
    if resumed_at is None:
        return None
    after = HogFlow.objects.get(team_id=team_id, pk=hog_flow_id)
    log_workflow_activity(
        actor=actor,
        workflow_id=hog_flow_id,
        name=after.name,
        activity="email_sending_resumed",
        previous=field_values(before),
        current=field_values(after),
    )
    return resumed_at


def bulk_delete_archived_workflows(
    *, project_id: int, workflow_ids: list[UUID], user_access_control: UserAccessControl, actor: WorkflowActor
) -> list[tuple[UUID, Optional[str]]]:
    """Delete the archived workflows among `workflow_ids` that the caller may edit, and log each one.
    Returns the id and name of each deleted workflow."""
    # Deleting needs object-level editor access, as the single delete does. An access filter only drops
    # invisible workflows, so an object-specific viewer override would otherwise be bulk-deletable.
    candidates = list(
        HogFlow.objects.filter(team__project_id=project_id, id__in=workflow_ids, status=HogFlow.State.ARCHIVED)
    )
    user_access_control.preload_object_access_controls(cast("list[models.Model]", candidates))
    deletable = [
        flow for flow in candidates if user_access_control.check_access_level_for_object(flow, required_level="editor")
    ]
    # Lock the rows so the audit entries match exactly what this call deletes (a concurrently removed row
    # gets no entry), and share the delete's transaction so a failed delete rolls its audit rows back.
    with transaction.atomic():
        deleted_ids = set(
            HogFlow.objects.select_for_update()
            .filter(team__project_id=project_id, id__in=[flow.id for flow in deletable])
            .values_list("id", flat=True)
        )
        HogFlow.objects.filter(team__project_id=project_id, id__in=deleted_ids).delete()
        deleted = [(flow.id, flow.name) for flow in deletable if flow.id in deleted_ids]
        for flow_id, name in deleted:
            log_workflow_activity(actor=actor, workflow_id=flow_id, name=name, activity="deleted")
    return deleted
