"""Facade for warehouse_suggestions."""

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from ..logic import suggestions
from ..logic.access import SubjectAccess, readable_table_ids, visible_suggestions
from ..logic.flags import is_warehouse_suggestions_enabled
from ..logic.payloads import payload_from_json, payload_view, source_table_ids
from ..logic.rules import RULES
from ..models import WarehouseSuggestion, WarehouseSuggestionTeamConfig
from .contracts import (
    SubjectEditAccessRequiredError,
    Suggestion,
    SuggestionDraft,
    SuggestionNotFoundError,
    SuggestionPage,
    SuggestionPayloadView,
    SuggestionReviewer,
    SuggestionStatus,
)
from .enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

__all__ = [
    "dismiss_suggestion",
    "get_suggestion",
    "is_warehouse_suggestions_enabled",
    "list_suggestions",
    "resume_suggestion",
    "suggestion_status",
    "upsert_suggestions",
]


def upsert_suggestions(team_id: int, drafts: Sequence[SuggestionDraft]) -> None:
    suggestions.upsert_suggestions(team_id, drafts)


def list_suggestions(
    team_id: int,
    user_access_control: "UserAccessControl",
    *,
    kind: WarehouseSuggestionKind | None,
    status: WarehouseSuggestionStatus | None,
    limit: int,
    offset: int,
) -> SuggestionPage:
    visible, access = visible_suggestions(team_id, user_access_control, kind=kind, status=status)
    page = list(visible[offset : offset + limit])
    return SuggestionPage(count=visible.count(), results=_to_contracts(team_id, user_access_control, page, access))


def suggestion_status(team_id: int) -> SuggestionStatus:
    config = WarehouseSuggestionTeamConfig.objects.filter(team_id=team_id).first() or WarehouseSuggestionTeamConfig()
    return SuggestionStatus(
        enabled=config.enabled,
        eligible=config.eligible,
        days_with_data=config.days_with_data,
        window_days=RULES.window_days,
        paused_reason=config.paused_reason,
        refreshed_at=config.last_run_at,
    )


def get_suggestion(team_id: int, user_access_control: "UserAccessControl", suggestion_id: UUID) -> Suggestion:
    row, access = _visible_suggestion(team_id, user_access_control, suggestion_id)
    (suggestion,) = _to_contracts(team_id, user_access_control, [row], access)
    return suggestion


def dismiss_suggestion(
    team_id: int,
    user_access_control: "UserAccessControl",
    suggestion_id: UUID,
    *,
    user_id: int,
    reason: WarehouseSuggestionDismissalReason,
    note: str | None,
) -> Suggestion:
    return _decide(
        team_id,
        user_access_control,
        suggestion_id,
        WarehouseSuggestionStatus.DISMISSED,
        user_id=user_id,
        reason=reason,
        note=note,
    )


def resume_suggestion(
    team_id: int, user_access_control: "UserAccessControl", suggestion_id: UUID, *, user_id: int
) -> Suggestion:
    return _decide(team_id, user_access_control, suggestion_id, WarehouseSuggestionStatus.PROPOSED, user_id=user_id)


def _decide(
    team_id: int,
    user_access_control: "UserAccessControl",
    suggestion_id: UUID,
    new_status: WarehouseSuggestionStatus,
    *,
    user_id: int,
    reason: WarehouseSuggestionDismissalReason | None = None,
    note: str | None = None,
) -> Suggestion:
    row, access = _visible_suggestion(team_id, user_access_control, suggestion_id)
    if not access.can_act_on(row):
        raise SubjectEditAccessRequiredError(WarehouseSuggestionSubjectKind(row.subject_kind))
    decided = suggestions.transition_to(
        row.id,
        team_id,
        new_status,
        user_id=user_id,
        reason=reason,
        note=note,
        transitions=suggestions.HUMAN_TRANSITIONS,
    )
    (suggestion,) = _to_contracts(team_id, user_access_control, [decided], access)
    return suggestion


def _visible_suggestion(
    team_id: int, user_access_control: "UserAccessControl", suggestion_id: UUID
) -> tuple[WarehouseSuggestion, SubjectAccess]:
    visible, access = visible_suggestions(team_id, user_access_control, suggestion_id=suggestion_id)
    row = visible.first()
    if row is None:
        raise SuggestionNotFoundError(suggestion_id)
    return row, access


def _to_contracts(
    team_id: int,
    user_access_control: "UserAccessControl",
    rows: list[WarehouseSuggestion],
    access: SubjectAccess,
) -> list[Suggestion]:
    stored = {
        row.id: payload_from_json(WarehouseSuggestionKind(row.kind), row.payload_version, row.payload) for row in rows
    }
    readable = readable_table_ids(team_id, user_access_control, source_table_ids(stored.values()))
    return [_to_contract(row, access, payload_view(stored[row.id], readable)) for row in rows]


def _to_contract(row: WarehouseSuggestion, access: SubjectAccess, payload: SuggestionPayloadView) -> Suggestion:
    return Suggestion(
        id=row.id,
        kind=WarehouseSuggestionKind(row.kind),
        subject_kind=WarehouseSuggestionSubjectKind(row.subject_kind),
        subject_id=row.subject_id,
        payload=payload,
        payload_version=row.payload_version,
        evidence=row.evidence,
        evidence_window_start=row.evidence_window_start,
        evidence_window_end=row.evidence_window_end,
        last_seen_at=row.last_seen_at,
        score=row.score,
        status=WarehouseSuggestionStatus(row.status),
        surfaced_at=row.surfaced_at,
        reviewed_by=_to_reviewer(row),
        reviewed_at=row.reviewed_at,
        dismissal_reason=WarehouseSuggestionDismissalReason(row.dismissal_reason) if row.dismissal_reason else None,
        dismissal_note=row.dismissal_note,
        created_asset=row.created_asset,
        asset_outcome=WarehouseSuggestionAssetOutcome(row.asset_outcome) if row.asset_outcome else None,
        can_act=access.can_act_on(row),
    )


def _to_reviewer(row: WarehouseSuggestion) -> SuggestionReviewer | None:
    if row.reviewed_by is None:
        return None
    return SuggestionReviewer(id=row.reviewed_by.id, first_name=row.reviewed_by.first_name, email=row.reviewed_by.email)
