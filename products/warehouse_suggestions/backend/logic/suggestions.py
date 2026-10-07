from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from ..facade.contracts import SuggestionAlreadyDecidedError, SuggestionDraft
from ..facade.enums import WarehouseSuggestionDismissalReason, WarehouseSuggestionStatus
from ..models import WarehouseSuggestion

Transitions = Mapping[WarehouseSuggestionStatus, frozenset[WarehouseSuggestionStatus]]

ALLOWED_TRANSITIONS: Transitions = {
    WarehouseSuggestionStatus.PROPOSED: frozenset(
        {
            WarehouseSuggestionStatus.ACCEPTED,
            WarehouseSuggestionStatus.DISMISSED,
            WarehouseSuggestionStatus.EXPIRED,
            WarehouseSuggestionStatus.AUTO_RESOLVED,
        }
    ),
    WarehouseSuggestionStatus.DISMISSED: frozenset({WarehouseSuggestionStatus.PROPOSED}),
    WarehouseSuggestionStatus.EXPIRED: frozenset({WarehouseSuggestionStatus.PROPOSED}),
}

HUMAN_TRANSITIONS: Transitions = {
    WarehouseSuggestionStatus.PROPOSED: frozenset(
        {WarehouseSuggestionStatus.ACCEPTED, WarehouseSuggestionStatus.DISMISSED}
    ),
    WarehouseSuggestionStatus.DISMISSED: frozenset({WarehouseSuggestionStatus.PROPOSED}),
}

HUMAN_DECISIONS = frozenset({WarehouseSuggestionStatus.ACCEPTED, WarehouseSuggestionStatus.DISMISSED})

DRAFT_FIELDS_UPDATED_ON_INGEST = (
    "payload",
    "payload_version",
    "rules_version",
    "evidence",
    "evidence_window_start",
    "evidence_window_end",
    "score",
    "score_inputs",
    "run_id",
)


def transition_to(
    suggestion_id: UUID,
    team_id: int,
    new_status: WarehouseSuggestionStatus,
    *,
    user_id: int | None,
    reason: WarehouseSuggestionDismissalReason | None = None,
    note: str | None = None,
    transitions: Transitions = ALLOWED_TRANSITIONS,
) -> WarehouseSuggestion:
    with transaction.atomic():
        suggestion = WarehouseSuggestion.objects.for_team(team_id).select_for_update().get(id=suggestion_id)
        current = WarehouseSuggestionStatus(suggestion.status)
        if new_status not in transitions.get(current, frozenset()):
            raise SuggestionAlreadyDecidedError(current, new_status)
        suggestion.status = new_status
        if new_status == WarehouseSuggestionStatus.PROPOSED:
            _clear_review(suggestion)
        if new_status in HUMAN_DECISIONS:
            _record_review(suggestion, user_id)
        if new_status == WarehouseSuggestionStatus.DISMISSED:
            _record_dismissal(suggestion, reason, note)
        suggestion.save()
    return suggestion


def _clear_review(suggestion: WarehouseSuggestion) -> None:
    suggestion.reviewed_by = None
    suggestion.reviewed_at = None
    suggestion.dismissal_reason = None
    suggestion.dismissal_note = None
    suggestion.dismissed_at_score = None


def _record_review(suggestion: WarehouseSuggestion, user_id: int | None) -> None:
    suggestion.reviewed_by_id = user_id
    suggestion.reviewed_at = timezone.now()


def _record_dismissal(
    suggestion: WarehouseSuggestion, reason: WarehouseSuggestionDismissalReason | None, note: str | None
) -> None:
    suggestion.dismissal_reason = reason
    suggestion.dismissal_note = note
    suggestion.dismissed_at_score = suggestion.score


def upsert_suggestions(team_id: int, drafts: Sequence[SuggestionDraft]) -> None:
    team_id = resolve_effective_team_id(team_id)
    suggestions = WarehouseSuggestion.objects.for_team(team_id, canonical=True)
    seen_at = timezone.now()
    drafts_by_fingerprint = {draft.fingerprint: draft for draft in drafts}
    with transaction.atomic():
        suggestions.bulk_create(
            [_new_suggestion(team_id, draft, seen_at) for draft in drafts_by_fingerprint.values()],
            ignore_conflicts=True,
        )
        candidates = suggestions.select_for_update().filter(
            fingerprint__in=drafts_by_fingerprint,
            status=WarehouseSuggestionStatus.PROPOSED,
            last_seen_at__lt=seen_at,
        )
        refreshed = [
            _refresh(row, drafts_by_fingerprint[row.fingerprint], seen_at)
            for row in candidates
            if _is_refreshed_by(row, drafts_by_fingerprint[row.fingerprint])
        ]
        suggestions.bulk_update(refreshed, [*DRAFT_FIELDS_UPDATED_ON_INGEST, "last_seen_at"])


def _is_refreshed_by(row: WarehouseSuggestion, draft: SuggestionDraft) -> bool:
    same_subject = (row.kind, row.subject_kind, row.subject_id) == (draft.kind, draft.subject_kind, draft.subject_id)
    return same_subject and draft.evidence_window_end >= row.evidence_window_end


def _refresh(row: WarehouseSuggestion, draft: SuggestionDraft, seen_at: datetime) -> WarehouseSuggestion:
    for field in DRAFT_FIELDS_UPDATED_ON_INGEST:
        setattr(row, field, getattr(draft, field))
    row.last_seen_at = seen_at
    return row


def _new_suggestion(team_id: int, draft: SuggestionDraft, seen_at: datetime) -> WarehouseSuggestion:
    return WarehouseSuggestion(team_id=team_id, last_seen_at=seen_at, **asdict(draft))
