"""Whole workflows PostHog suggests to a project, and what a person does with them."""

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.workflows.backend.facade.contracts import (
    NewWorkflowIdea,
    WorkflowIdeaAlreadyResolved,
    WorkflowIdeaNotFound,
    WorkflowIdeaRecord,
    WorkflowIdeaWorkflowMismatch,
)
from products.workflows.backend.models import HogFlow, WorkflowIdea


def _record(row: WorkflowIdea) -> WorkflowIdeaRecord:
    return WorkflowIdeaRecord(
        id=row.id,
        team_id=row.team_id,
        key=row.key,
        title=row.title,
        rationale=row.rationale,
        status=row.status,
        evidence=row.evidence,
        definition=row.definition,
        created_at=row.created_at,
        hog_flow_id=row.hog_flow_id,
        resolved_at=row.resolved_at,
    )


def list_open_ideas(*, team_id: int, source: str) -> list[WorkflowIdeaRecord]:
    """Ideas from `source` still waiting for a decision, oldest first."""
    rows = WorkflowIdea.objects.for_team(team_id).filter(status=WorkflowIdea.Status.SUGGESTED, source=source)
    return [_record(row) for row in rows.order_by("created_at")]


def get_open_idea(*, team_id: int, idea_id: str, source: str) -> WorkflowIdeaRecord | None:
    try:
        UUID(idea_id)
    except ValueError:
        return None
    row = (
        WorkflowIdea.objects.for_team(team_id)
        .filter(id=idea_id, status=WorkflowIdea.Status.SUGGESTED, source=source)
        .first()
    )
    return _record(row) if row is not None else None


def list_ideas_in_draft(*, team_id: int, source: str) -> list[WorkflowIdeaRecord]:
    """Used ideas from `source` whose workflow is still a draft, oldest first."""
    rows = WorkflowIdea.objects.for_team(team_id).filter(
        status=WorkflowIdea.Status.ACCEPTED, source=source, hog_flow__status=HogFlow.State.DRAFT
    )
    return [_record(row) for row in rows.order_by("created_at")]


def create_ideas(
    *, team_id: int, items: Iterable[NewWorkflowIdea], source: str, source_ref: str | None = None
) -> list[WorkflowIdeaRecord]:
    """Stores new ideas and skips any key the project was already given, so a dismissal sticks."""
    items = list(items)
    if any(not item.key.strip() for item in items):
        raise ValueError("Every workflow idea needs a non-blank key.")
    # The model saves rows on the project, so the lookup and the insert must both use the project id.
    project_id = resolve_effective_team_id(team_id)
    created = []
    for item in items:
        row, was_created = WorkflowIdea.objects.for_team(project_id, canonical=True).get_or_create(
            team_id=project_id,
            key=item.key.strip(),
            defaults={
                "title": item.title,
                "rationale": item.rationale,
                "definition": item.definition,
                "evidence": item.evidence,
                "source": source,
                "source_ref": source_ref,
            },
        )
        if was_created:
            created.append(_record(row))
    return created


def notify_new_ideas(*, team_id: int, idea_ids: Iterable[UUID]) -> bool:
    """Tells the project once about ideas it has not heard about yet."""
    with transaction.atomic():
        # Claim the ideas first, so an overlapping run finds them taken and the locks are not held while
        # the notification checks its flag over the network.
        pending = list(
            WorkflowIdea.objects.for_team(team_id)
            .select_for_update()
            .filter(id__in=list(idea_ids), notified_at__isnull=True, status=WorkflowIdea.Status.SUGGESTED)
            .order_by("created_at")
        )
        if not pending:
            return False
        claimed = [row.id for row in pending]
        WorkflowIdea.objects.for_team(team_id).filter(id__in=claimed).update(notified_at=timezone.now())
    count = len(pending)
    event = None
    try:
        event = create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.WORKFLOW_IDEAS,
                title=f"PostHog drafted {count} email workflow{'s' if count != 1 else ''} from your events",
                body="; ".join(row.title for row in pending) + ". Review the emails and turn on the ones you want.",
                target_type=TargetType.TEAM,
                target_id=str(team_id),
                # Only people who can view workflows hear about ideas, as only they can open them.
                resource_type="hog_flow",
                source_url="/workflows",
            )
        )
    finally:
        # If nothing was sent, for any reason, give the ideas back for a later run.
        if event is None:
            WorkflowIdea.objects.for_team(team_id).filter(id__in=claimed).update(notified_at=None)
    return event is not None


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
    *, team_id: int, idea_id: str, hog_flow_id: str, user_id: int, access: UserAccessControl
) -> WorkflowIdeaRecord:
    """Records the draft a person created from the idea. The draft itself goes through the workflow API."""
    with transaction.atomic():
        row = _lock_open(team_id, idea_id)
        # Locked so two ideas accepted at once cannot both claim the same draft.
        hog_flow = (
            HogFlow.objects.select_for_update()
            .filter(team_id=team_id, id=hog_flow_id, status=HogFlow.State.DRAFT)
            .first()
        )
        if (
            hog_flow is None
            or not access.check_access_level_for_object(hog_flow, required_level="editor")
            or WorkflowIdea.objects.for_team(team_id).filter(hog_flow=hog_flow).exists()
        ):
            raise WorkflowIdeaWorkflowMismatch()
        row.status = WorkflowIdea.Status.ACCEPTED
        row.hog_flow = hog_flow
        row.resolved_at = timezone.now()
        row.resolved_by_id = user_id
        row.save(update_fields=["status", "hog_flow", "resolved_at", "resolved_by"])
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
