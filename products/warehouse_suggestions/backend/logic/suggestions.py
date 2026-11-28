from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from ..facade.contracts import (
    CreatedAsset,
    DeletionAsset,
    SuggestionAlreadyDecidedError,
    SuggestionDraft,
    UnmaterializationAsset,
)
from ..facade.enums import WarehouseSuggestionDismissalReason, WarehouseSuggestionKind, WarehouseSuggestionStatus
from ..models import WarehouseSuggestion
from .payloads import payload_to_json

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
    WarehouseSuggestionStatus.AUTO_RESOLVED: frozenset({WarehouseSuggestionStatus.PROPOSED}),
}

HUMAN_TRANSITIONS: Transitions = {
    WarehouseSuggestionStatus.PROPOSED: frozenset(
        {WarehouseSuggestionStatus.ACCEPTED, WarehouseSuggestionStatus.DISMISSED}
    ),
    WarehouseSuggestionStatus.DISMISSED: frozenset({WarehouseSuggestionStatus.PROPOSED}),
}

HUMAN_DECISIONS = frozenset({WarehouseSuggestionStatus.ACCEPTED, WarehouseSuggestionStatus.DISMISSED})


class DeprecateChoice(StrEnum):
    MARK_DEPRECATED = "mark_deprecated"
    ONLY_STOP_REFRESHES = "only_stop_refreshes"
    DELETE = "delete"


CERTIFICATION_ID_FIELD = "certification_id"
DEPRECATE_CHOICE_BY_ASSET_FIELDS: Mapping[frozenset[str], DeprecateChoice] = {
    frozenset(field.name for field in fields(UnmaterializationAsset)): DeprecateChoice.ONLY_STOP_REFRESHES,
    frozenset(field.name for field in fields(DeletionAsset)): DeprecateChoice.DELETE,
}

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
    created_asset: CreatedAsset | None = None,
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
        if created_asset is not None:
            suggestion.created_asset = asdict(created_asset)
        suggestion.save()
    return suggestion


def _clear_review(suggestion: WarehouseSuggestion) -> None:
    suggestion.reviewed_by = None
    suggestion.reviewed_at = None
    suggestion.dismissal_reason = None
    suggestion.dismissal_note = None
    suggestion.dismissed_at_score = None
    suggestion.realized_seconds_saved_per_month = None
    suggestion.realized_bytes_saved_per_month = None


def _record_review(suggestion: WarehouseSuggestion, user_id: int | None) -> None:
    suggestion.reviewed_by_id = user_id
    suggestion.reviewed_at = timezone.now()


def _record_dismissal(
    suggestion: WarehouseSuggestion, reason: WarehouseSuggestionDismissalReason | None, note: str | None
) -> None:
    suggestion.dismissal_reason = reason
    suggestion.dismissal_note = note
    suggestion.dismissed_at_score = suggestion.score


def deprecate_choice(kind: str, created_asset: Mapping[str, object] | None) -> DeprecateChoice | None:
    if kind != WarehouseSuggestionKind.DEPRECATE or not created_asset:
        return None
    if CERTIFICATION_ID_FIELD in created_asset:
        return DeprecateChoice.MARK_DEPRECATED
    return DEPRECATE_CHOICE_BY_ASSET_FIELDS.get(frozenset(created_asset))


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
    values = _draft_values(draft)
    for field in DRAFT_FIELDS_UPDATED_ON_INGEST:
        setattr(row, field, values[field])
    row.last_seen_at = seen_at
    return row


def _new_suggestion(team_id: int, draft: SuggestionDraft, seen_at: datetime) -> WarehouseSuggestion:
    return WarehouseSuggestion(team_id=team_id, last_seen_at=seen_at, **_draft_values(draft))


def _draft_values(draft: SuggestionDraft) -> dict[str, Any]:
    return {
        field.name: payload_to_json(draft.payload) if field.name == "payload" else getattr(draft, field.name)
        for field in fields(draft)
    }
