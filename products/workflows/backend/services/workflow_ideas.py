"""Whole workflows PostHog suggests to a project, and what a person does with them."""

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.workflows.backend.facade.contracts import (
    NewWorkflowIdea,
    WorkflowIdeaAlreadyResolved,
    WorkflowIdeaNotFound,
    WorkflowIdeaRecord,
    WorkflowIdeaWorkflowMismatch,
)
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models import HogFlow, WorkflowIdea

VALUE_TIER_ORDER = {"revenue": 0, "activation": 1, "retention": 2, "engagement": 3}


def _record(row: WorkflowIdea) -> WorkflowIdeaRecord:
    return WorkflowIdeaRecord(
        id=row.id,
        team_id=row.team_id,
        key=row.key,
        title=row.title,
        rationale=row.rationale,
        value_tier=row.value_tier,
        status=row.status,
        evidence=row.evidence,
        definition=row.definition,
        created_at=row.created_at,
        hog_flow_id=row.hog_flow_id,
        resolved_at=row.resolved_at,
    )


def list_open_ideas(*, team_id: int) -> list[WorkflowIdeaRecord]:
    """Ideas still waiting for a decision, the best first bet for the project first."""
    rows = list(WorkflowIdea.objects.for_team(team_id).filter(status=WorkflowIdea.Status.SUGGESTED))
    rows.sort(
        # The idea's own priority first: the author ranks the best first bet for this project.
        key=lambda row: (row.evidence.get("priority") or 99, VALUE_TIER_ORDER.get(row.value_tier, 99)),
    )
    return [_record(row) for row in rows]


def mark_viewed(*, team_id: int, idea_ids: Iterable[str]) -> int:
    return (
        WorkflowIdea.objects.for_team(team_id)
        .filter(id__in=list(idea_ids), first_viewed_at__isnull=True)
        .update(first_viewed_at=timezone.now())
    )


def create_ideas(
    *, team_id: int, items: Iterable[NewWorkflowIdea], source: str, source_ref: str | None = None
) -> list[WorkflowIdeaRecord]:
    """Stores new ideas and skips any key the project was already given, so a dismissal sticks."""
    created = []
    for item in items:
        row, was_created = WorkflowIdea.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            key=item.key,
            defaults={
                "title": item.title,
                "rationale": item.rationale,
                "value_tier": item.value_tier,
                "definition": item.definition,
                "evidence": item.evidence,
                "source": source,
                "source_ref": source_ref,
            },
        )
        if was_created:
            created.append(_record(row))
    return created


def _lock_open(team_id: int, idea_id: str) -> WorkflowIdea:
    try:
        UUID(idea_id)
    except ValueError:
        raise WorkflowIdeaNotFound()
    row = WorkflowIdea.objects.for_team(team_id).select_for_update().filter(id=idea_id).first()
    if row is None:
        raise WorkflowIdeaNotFound()
    if row.status != WorkflowIdea.Status.SUGGESTED:
        raise WorkflowIdeaAlreadyResolved()
    return row


def accept_idea(
    *, team_id: int, idea_id: str, hog_flow_id: str, user_id: int, site_url: str | None = None
) -> WorkflowIdeaRecord:
    """Records the draft a person created from the idea. The draft itself goes through the workflow API."""
    with transaction.atomic():
        row = _lock_open(team_id, idea_id)
        hog_flow = HogFlow.objects.filter(team_id=team_id, id=hog_flow_id).first()
        if hog_flow is None or hog_flow.origin_product != HogFlowOriginProduct.IDEAS:
            raise WorkflowIdeaWorkflowMismatch()
        row.status = WorkflowIdea.Status.ACCEPTED
        row.hog_flow = hog_flow
        row.resolved_at = timezone.now()
        row.resolved_by_id = user_id
        if site_url:
            row.evidence = {**row.evidence, "site_url": site_url}
        row.save(update_fields=["status", "hog_flow", "resolved_at", "resolved_by", "evidence"])
    return _record(row)


def dismiss_idea(*, team_id: int, idea_id: str, user_id: int, reason: str = "") -> WorkflowIdeaRecord:
    with transaction.atomic():
        row = _lock_open(team_id, idea_id)
        row.status = WorkflowIdea.Status.DISMISSED
        row.dismiss_reason = reason.strip()
        row.resolved_at = timezone.now()
        row.resolved_by_id = user_id
        row.save(update_fields=["status", "dismiss_reason", "resolved_at", "resolved_by"])
    return _record(row)
