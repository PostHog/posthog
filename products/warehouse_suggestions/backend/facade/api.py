"""Facade for warehouse_suggestions."""

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from ..logic import suggestions
from ..logic.access import SubjectAccess, visible_suggestions
from ..logic.flags import is_warehouse_suggestions_enabled
from ..models import WarehouseSuggestion
from .contracts import (
    SubjectEditAccessRequiredError,
    Suggestion,
    SuggestionDraft,
    SuggestionNotFoundError,
    SuggestionPage,
    SuggestionReviewer,
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
    page = visible[offset : offset + limit]
    return SuggestionPage(count=visible.count(), results=[_to_contract(row, access) for row in page])


def get_suggestion(team_id: int, user_access_control: "UserAccessControl", suggestion_id: UUID) -> Suggestion:
    row, access = _visible_suggestion(team_id, user_access_control, suggestion_id)
    return _to_contract(row, access)


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
    return _to_contract(decided, access)


def _visible_suggestion(
    team_id: int, user_access_control: "UserAccessControl", suggestion_id: UUID
) -> tuple[WarehouseSuggestion, SubjectAccess]:
    visible, access = visible_suggestions(team_id, user_access_control, suggestion_id=suggestion_id)
    row = visible.first()
    if row is None:
        raise SuggestionNotFoundError(suggestion_id)
    return row, access


def _to_contract(row: WarehouseSuggestion, access: SubjectAccess) -> Suggestion:
    return Suggestion(
        id=row.id,
        kind=WarehouseSuggestionKind(row.kind),
        subject_kind=WarehouseSuggestionSubjectKind(row.subject_kind),
        subject_id=row.subject_id,
        payload=row.payload,
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
