"""Stopping the active workflows of teams that staff shut down for abuse."""

from collections.abc import Collection

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def active_workflow_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        HogFlow.objects.filter(team_id__in=team_ids, status=HogFlow.State.ACTIVE)
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [str(workflow_id) for workflow_id in rows]


def move_workflow_to_draft(workflow_id: str, *, team_ids: Collection[int]) -> bool:
    workflow = HogFlow.objects.filter(team_id__in=team_ids, id=workflow_id, status=HogFlow.State.ACTIVE).first()
    if workflow is None:
        return False
    workflow.status = HogFlow.State.DRAFT
    # A save, not a bulk update: the save signal is what makes the workflow workers drop it.
    workflow.save(update_fields=["status"])
    return True
