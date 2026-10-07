"""Contract types for warehouse_suggestions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

from .enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)


@frozen
class SuggestionDraft:
    kind: WarehouseSuggestionKind
    fingerprint: str
    subject_kind: WarehouseSuggestionSubjectKind
    subject_id: UUID
    payload: dict[str, Any]
    payload_version: int
    rules_version: str
    evidence: dict[str, Any]
    evidence_window_start: datetime
    evidence_window_end: datetime
    score: float
    score_inputs: dict[str, Any]
    run_id: str


@frozen
class SuggestionReviewer:
    id: int
    first_name: str
    email: str


@frozen
class Suggestion:
    id: UUID
    kind: WarehouseSuggestionKind
    subject_kind: WarehouseSuggestionSubjectKind
    subject_id: UUID
    payload: dict[str, Any]
    payload_version: int
    evidence: dict[str, Any]
    evidence_window_start: datetime
    evidence_window_end: datetime
    last_seen_at: datetime
    score: float
    status: WarehouseSuggestionStatus
    surfaced_at: datetime | None
    reviewed_by: SuggestionReviewer | None
    reviewed_at: datetime | None
    dismissal_reason: WarehouseSuggestionDismissalReason | None
    dismissal_note: str | None
    created_asset: dict[str, Any] | None
    asset_outcome: WarehouseSuggestionAssetOutcome | None
    can_act: bool


@frozen
class SuggestionPage:
    count: int
    results: list[Suggestion]


class SuggestionNotFoundError(Exception):
    pass


class SubjectEditAccessRequiredError(Exception):
    def __init__(self, subject_kind: WarehouseSuggestionSubjectKind) -> None:
        super().__init__(subject_kind)
        self.subject_kind = subject_kind


class SuggestionAlreadyDecidedError(Exception):
    def __init__(self, current: WarehouseSuggestionStatus, requested: WarehouseSuggestionStatus) -> None:
        super().__init__(f"This suggestion is {current.label.lower()} and cannot become {requested.label.lower()}.")
