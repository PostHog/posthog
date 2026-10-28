"""Contract types for warehouse_suggestions."""

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from posthog.dataclasses import frozen

from .enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionRefreshIntervalBasis,
    WarehouseSuggestionRefreshMode,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)

PAYLOAD_VERSION = 1
WAREHOUSE_SCOPE_OBJECT: Final = "warehouse_objects"
SUBJECT_SCOPE_OBJECTS = {
    WarehouseSuggestionSubjectKind.SAVED_QUERY: "warehouse_view",
    WarehouseSuggestionSubjectKind.TABLE: "warehouse_table",
}


@frozen
class SubjectKinds:
    readable: frozenset[WarehouseSuggestionSubjectKind]
    actionable: frozenset[WarehouseSuggestionSubjectKind]


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
    refresh_mode: WarehouseSuggestionRefreshMode = WarehouseSuggestionRefreshMode.FULL
    incremental_key: str | None = None
    unique_key: tuple[str, ...] = ()
    lookback_seconds: int = 0
    refresh_interval_basis: WarehouseSuggestionRefreshIntervalBasis | None = None
    recomputed_by_views: int = 0


@frozen
class UnmaterializePayload:
    subject_name: str
    refresh_seconds_per_month: float
    refresh_bytes_per_month: float
    live_seconds_per_month: float
    live_bytes_per_month: float
    read_seconds: float
    query_fingerprint: str


SuggestionPayload = CertifyPayload | DeprecatePayload | MaterializePayload | UnmaterializePayload


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
    refresh_mode: WarehouseSuggestionRefreshMode = WarehouseSuggestionRefreshMode.FULL
    incremental_key: str | None = None
    unique_key: tuple[str, ...] = ()
    lookback_seconds: int = 0
    refresh_interval_basis: WarehouseSuggestionRefreshIntervalBasis | None = None
    recomputed_by_views: int = 0


SuggestionPayloadView = CertifyPayload | DeprecatePayload | MaterializeSuggestionPayload | UnmaterializePayload


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
    status: WarehouseSuggestionStatus
    surfaced_at: datetime | None
    reviewed_by: SuggestionReviewer | None
    reviewed_at: datetime | None
    dismissal_reason: WarehouseSuggestionDismissalReason | None
    dismissal_note: str | None
    created_asset: dict[str, Any] | None
    asset_outcome: WarehouseSuggestionAssetOutcome | None
    realized_seconds_saved_per_month: float | None
    realized_bytes_saved_per_month: float | None
    can_act: bool
    subject_source_id: UUID | None = None
    subject_schema_id: UUID | None = None
    assignee: SuggestionReviewer | None = None


@frozen
class CertificationAsset:
    certification_id: str
    stopped_materialization: bool = False


@frozen
class MaterializationAsset:
    saved_query_id: str
    refresh_interval_seconds: int
    refresh_mode: WarehouseSuggestionRefreshMode
    incremental_key: str | None
    unique_key: tuple[str, ...]
    lookback_seconds: int


@frozen
class AcceptOptions:
    """Payload values a person chose instead of the suggested ones. None keeps the suggested value."""

    refresh_interval_seconds: int | None = None
    refresh_mode: WarehouseSuggestionRefreshMode | None = None
    incremental_key: str | None = None
    unique_key: tuple[str, ...] | None = None
    lookback_seconds: int | None = None
    keep_materialized: bool | None = None


@frozen
class UnmaterializationAsset:
    saved_query_id: str


CreatedAsset = CertificationAsset | MaterializationAsset | UnmaterializationAsset


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


class CatalogEditAccessRequiredError(Exception):
    pass


class SuggestionAlreadyDecidedError(Exception):
    def __init__(self, current: WarehouseSuggestionStatus, requested: WarehouseSuggestionStatus) -> None:
        super().__init__(f"This suggestion is {current.label.lower()} and cannot become {requested.label.lower()}.")


class UnsupportedPayloadVersionError(Exception):
    def __init__(self, payload_version: int) -> None:
        super().__init__(f"Suggestion payload version {payload_version} is not supported.")


class SuggestionSubjectGoneError(Exception):
    def __init__(self, subject_kind: WarehouseSuggestionSubjectKind) -> None:
        super().__init__(subject_kind)
        self.subject_kind = subject_kind


class SubjectAlreadyCertifiedError(Exception):
    def __init__(self, subject_kind: WarehouseSuggestionSubjectKind) -> None:
        super().__init__(subject_kind)
        self.subject_kind = subject_kind


class AcceptOptionRefusedError(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class SuggestionOutdatedError(Exception):
    pass


class AssigneeCannotActError(Exception):
    pass


class SuggestionNotOpenError(Exception):
    pass


class AcceptFailedError(Exception):
    pass
