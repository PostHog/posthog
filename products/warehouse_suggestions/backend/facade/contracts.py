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

PAYLOAD_VERSION = 1


@frozen
class SourceRef:
    name: str
    warehouse_table_id: UUID | None


@frozen
class CertifyPayload:
    subject_name: str


@frozen
class DeprecatePayload:
    subject_name: str
    refresh_seconds_per_month: float
    refresh_bytes_per_month: float


@frozen
class MaterializePayload:
    """The stored materialize payload, with the warehouse table id of each source."""

    subject_name: str
    refresh_interval_seconds: int
    saves_seconds_per_month: float
    saves_bytes_per_month: float
    freshness_today_seconds: int | None
    freshness_after_seconds: int
    live_sources: tuple[SourceRef, ...]
    unknown_sources: tuple[SourceRef, ...]


SuggestionPayload = CertifyPayload | DeprecatePayload | MaterializePayload


@frozen
class VisibleSources:
    names: tuple[str, ...]
    hidden_count: int


@frozen
class MaterializeSuggestionPayload:
    """The materialize payload a caller sees: the source names they can read, and a count of the others."""

    subject_name: str
    refresh_interval_seconds: int
    saves_seconds_per_month: float
    saves_bytes_per_month: float
    freshness_today_seconds: int | None
    freshness_after_seconds: int
    live_sources: VisibleSources
    unknown_sources: VisibleSources


SuggestionPayloadView = CertifyPayload | DeprecatePayload | MaterializeSuggestionPayload


@frozen
class SuggestionDraft:
    kind: WarehouseSuggestionKind
    fingerprint: str
    subject_kind: WarehouseSuggestionSubjectKind
    subject_id: UUID
    payload: SuggestionPayload
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
    payload: SuggestionPayloadView
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
class SuggestionStatus:
    enabled: bool
    eligible: bool
    days_with_data: int
    window_days: int
    paused_reason: str | None
    refreshed_at: datetime | None


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


class UnsupportedPayloadVersionError(Exception):
    def __init__(self, payload_version: int) -> None:
        super().__init__(f"Suggestion payload version {payload_version} is not supported.")
