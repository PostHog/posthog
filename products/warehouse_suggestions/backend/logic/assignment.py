from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.scopes import APIScopeObject

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)

from ..facade.contracts import AssigneeCannotActError, SuggestionNotOpenError
from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus, WarehouseSuggestionSubjectKind
from ..models import WarehouseSuggestion
from .access import CATALOG_KINDS, can_take
from .candidates.base import CandidateContext
from .payloads import payload_from_json

if TYPE_CHECKING:
    from posthog.models import Team

LOGGER = structlog.get_logger(__name__)

KIND_ACTIONS: Mapping[WarehouseSuggestionKind, str] = {
    WarehouseSuggestionKind.CERTIFY: "certify",
    WarehouseSuggestionKind.DEPRECATE: "deprecate",
    WarehouseSuggestionKind.MATERIALIZE: "materialize",
    WarehouseSuggestionKind.UNMATERIALIZE: "stop materializing",
}
NOTIFIED_RESOURCE: APIScopeObject = "warehouse_objects"
NOTIFICATION_TITLE_MAX_LENGTH = 255
ELLIPSIS = "…"
MANUAL_ASSIGNMENT_BODY = "Open it to see why PostHog suggests it, then accept or dismiss it."

Assignments = Mapping[User, Sequence[WarehouseSuggestion]]


def assign_surfaced(
    context: CandidateContext, team: "Team", surfaced: Sequence[WarehouseSuggestion]
) -> dict[User, list[WarehouseSuggestion]]:
    """Assign each unassigned surfaced view suggestion to the view's creator, when they can accept it."""
    creators = _view_creators(context, surfaced)
    assigned: defaultdict[User, list[WarehouseSuggestion]] = defaultdict(list)
    for row in surfaced:
        assignee = _surfaced_assignee(team, row, creators.get(row.subject_id))
        if not _assign_if_unchanged(team, row, assignee):
            continue
        row.assignee = assignee
        if assignee is not None:
            assigned[assignee].append(row)
    return assigned


def _assign_if_unchanged(team: "Team", row: WarehouseSuggestion, assignee: User | None) -> bool:
    """Write `assignee` only if nobody decided or reassigned the suggestion since the job read it."""
    return bool(
        WarehouseSuggestion.objects.for_team(team.pk)
        .filter(id=row.id, status=WarehouseSuggestionStatus.PROPOSED, assignee_id=row.assignee_id)
        .update(assignee=assignee)
    )


@frozen
class Assignment:
    suggestion: WarehouseSuggestion
    changed: bool


def assign(team: "Team", suggestion_id: UUID, assignee_id: int | None, *, assigned_by: User) -> Assignment:
    with transaction.atomic():
        suggestion = WarehouseSuggestion.objects.for_team(team.pk).select_for_update().get(id=suggestion_id)
        if suggestion.status != WarehouseSuggestionStatus.PROPOSED:
            raise SuggestionNotOpenError()
        if suggestion.assignee_id == assignee_id:
            return Assignment(suggestion=suggestion, changed=False)
        assignee = _assignable_user(team, suggestion, assignee_id)
        suggestion.assignee = assignee
        suggestion.save(update_fields=["assignee"])
    if assignee is not None and assignee != assigned_by:
        notify_assigned(team, suggestion, assignee, assigned_by=assigned_by)
    return Assignment(suggestion=suggestion, changed=True)


def _assignable_user(team: "Team", suggestion: WarehouseSuggestion, assignee_id: int | None) -> User | None:
    if assignee_id is None:
        return None
    assignee = User.objects.filter(id=assignee_id).first()
    if assignee is None or not can_take(team, assignee, suggestion):
        raise AssigneeCannotActError()
    return assignee


def notify_surfaced(team: "Team", assigned: Assignments, run_id: str) -> None:
    for assignee, rows in assigned.items():
        _notify(
            team,
            assignee,
            title=_surfaced_title(rows),
            body="\n".join(_sentence_case(_proposal(row)) for row in rows),
            source_url=_source_url(team, rows[0]),
            idempotency_key=f"warehouse-suggestions-{run_id}-{assignee.pk}",
        )


def notify_assigned(team: "Team", suggestion: WarehouseSuggestion, assignee: User, *, assigned_by: User) -> None:
    proposal = _proposal(suggestion)
    _notify(
        team,
        assignee,
        title=f"{assigned_by.first_name} assigned you a suggestion to {proposal}",
        body=f"{_sentence_case(proposal)}. {MANUAL_ASSIGNMENT_BODY}",
        source_url=_source_url(team, suggestion),
        resource_id=str(suggestion.subject_id),
    )


def _view_creators(context: CandidateContext, rows: Sequence[WarehouseSuggestion]) -> dict[UUID, User]:
    creator_ids = {
        row.subject_id: definition.created_by_id
        for row in rows
        if row.subject_kind == WarehouseSuggestionSubjectKind.SAVED_QUERY
        and (definition := context.inventory.saved_queries.get(row.subject_id)) is not None
        and definition.created_by_id is not None
    }
    users = User.objects.in_bulk(set(creator_ids.values()))
    return {subject_id: users[user_id] for subject_id, user_id in creator_ids.items() if user_id in users}


def _surfaced_assignee(team: "Team", row: WarehouseSuggestion, creator: User | None) -> User | None:
    """The current assignee if they can still accept the suggestion, else the view's creator if they can."""
    return next(
        (
            candidate
            for candidate in (row.assignee, creator)
            if candidate is not None and can_take(team, candidate, row)
        ),
        None,
    )


def _surfaced_title(rows: Sequence[WarehouseSuggestion]) -> str:
    if len(rows) == 1:
        return f"PostHog suggests you {_proposal(rows[0])}"
    return f"PostHog has {len(rows)} new warehouse suggestions for you"


def _proposal(row: WarehouseSuggestion) -> str:
    kind = WarehouseSuggestionKind(row.kind)
    subject_name = payload_from_json(kind, row.payload_version, row.payload).subject_name
    return f"{KIND_ACTIONS[kind]} {subject_name}"


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _source_url(team: "Team", row: WarehouseSuggestion) -> str:
    if row.kind in CATALOG_KINDS:
        return f"/project/{team.pk}/data-catalog?tab=certifications"
    return f"/project/{team.pk}/models?tab=models"


def _bounded_title(title: str) -> str:
    if len(title) <= NOTIFICATION_TITLE_MAX_LENGTH:
        return title
    return title[: NOTIFICATION_TITLE_MAX_LENGTH - len(ELLIPSIS)] + ELLIPSIS


def _notify(
    team: "Team",
    assignee: User,
    *,
    title: str,
    body: str,
    source_url: str,
    resource_id: str = "",
    idempotency_key: str | None = None,
) -> None:
    try:
        create_notification(
            NotificationData(
                team_id=team.pk,
                notification_type=NotificationType.WAREHOUSE_SUGGESTION_ASSIGNED,
                title=_bounded_title(title),
                body=body,
                target_type=TargetType.USER,
                target_id=str(assignee.pk),
                resource_type=NOTIFIED_RESOURCE,
                resource_id=resource_id,
                source_url=source_url,
                idempotency_key=idempotency_key,
            )
        )
    except Exception:
        LOGGER.exception("Could not send a warehouse suggestion notification", user_id=assignee.pk)
