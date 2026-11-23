"""Stopping the active workflows of teams that staff shut down for abuse."""

from collections.abc import Collection
from uuid import UUID

from django.db import transaction

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.hog_flow_writes import save_validated_workflow


def active_workflow_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        HogFlow.objects.filter(team_id__in=team_ids, status=HogFlow.State.ACTIVE)
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [str(workflow_id) for workflow_id in rows]


def move_workflow_to_draft(workflow_id: str, *, team_id: int) -> bool:
    with transaction.atomic():
        if not (
            HogFlow.objects.select_for_update()
            .filter(team_id=team_id, id=workflow_id, status=HogFlow.State.ACTIVE)
            .exists()
        ):
            return False
        # The live write path marks the workflow as disabled from active, so later content edits stage a
        # draft instead of landing on the live config, and its save signal makes the workflow workers drop it.
        save_validated_workflow(
            team_id=team_id, hog_flow_id=UUID(workflow_id), validated_data={"status": HogFlow.State.DRAFT}
        )
    return True
