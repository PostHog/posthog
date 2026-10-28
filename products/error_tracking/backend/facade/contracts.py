"""Contract types for error tracking.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax, same ``is_dataclass()`` compatibility, but with runtime validation on
construction so structural mistakes from mappers or internal callers surface at the
facade boundary instead of producing a malformed payload further downstream.
"""

from dataclasses import field
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic.dataclasses import dataclass

from posthog.enums import LabeledStrEnum

ERROR_TRACKING_ISSUE_SEVERITIES = ("low", "medium", "high", "critical")


class BuiltInFilterEvaluation(LabeledStrEnum):
    CLIENT = "client"
    SERVER = "server"


class IssueTrendDirection(LabeledStrEnum):
    NEW = "new"
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"


# Keep in sync with products/error_tracking/frontend/scenes/ErrorTrackingScene/banners/sourceMapsFixWizardLogic.ts.
SOURCE_MAPS_DOCS_URL = "https://posthog.com/docs/error-tracking/upload-source-maps"


@dataclass(frozen=True)
class DocumentEmbeddingTable:
    """One per-model embeddings table: the sharded storage table and the Distributed table that reads it."""

    sharded_table: str
    distributed_table: str


@dataclass(frozen=True)
class ExceptionSummary:
    exception_count: int
    ingestion_failure_count: int
    prev_exception_count: int


@dataclass(frozen=True)
class CrashFreeSummary:
    total_sessions: int
    crash_free_rate: float
    crash_free_rate_change: dict | None
    total_sessions_change: dict | None


@dataclass(frozen=True)
class ErrorTrackingIssueAssignee:
    id: int | str | None
    type: str


@dataclass(frozen=True)
class ErrorTrackingIssueCohort:
    id: int
    name: str


@dataclass(frozen=True)
class ErrorTrackingExternalReferenceIntegration:
    id: int
    kind: str
    display_name: str


@dataclass(frozen=True)
class ErrorTrackingExternalReference:
    id: UUID
    integration: ErrorTrackingExternalReferenceIntegration
    external_url: str
    external_id: str
    title: str


@dataclass(frozen=True)
class GitHubExternalReferenceJob:
    team_id: int
    installation_id: str
    repository_full_name: str
    number: int
    title: str
    resource_type: Literal["issue", "pull_request"]
    actor_login: str
    issue_id: UUID | None = None
    fingerprint: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (self.issue_id is None) == (self.fingerprint is None):
            raise ValueError("Provide exactly one PostHog issue identifier.")


@dataclass(frozen=True)
class ErrorTrackingFingerprint:
    id: UUID
    fingerprint: str
    issue_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class ErrorTrackingIssuePreview:
    id: UUID
    status: str
    severity: str | None
    name: str | None
    description: str | None
    first_seen: datetime | None
    assignee: ErrorTrackingIssueAssignee | None


@dataclass(frozen=True)
class ErrorTrackingIssue:
    id: UUID
    status: str
    severity: str | None
    name: str | None
    description: str | None
    first_seen: datetime | None
    assignee: ErrorTrackingIssueAssignee | None
    external_issues: list[ErrorTrackingExternalReference] = field(default_factory=list)
    cohort: ErrorTrackingIssueCohort | None = None


@dataclass(frozen=True)
class ErrorTrackingIssueUpdate:
    issue: ErrorTrackingIssue
    # Only the fields whose value differs from the stored one, so a no-op update lists nothing.
    changed_fields: list[str]


@dataclass(frozen=True)
class ErrorTrackingIssueMerge:
    result: Literal["merged", "no_source_issues", "stale_issues", "stale_fingerprints"]
    # Source issues that disappeared before the merge locked its rows are not counted.
    merged_issue_count: int


@dataclass(frozen=True)
class ErrorTrackingIssueForAssignmentNotification:
    id: UUID
    team_id: int
    status: str
    name: str | None
    description: str | None


@dataclass(frozen=True)
class ErrorTrackingIssueAssignmentNotification:
    id: UUID
    created_at: datetime
    issue: ErrorTrackingIssueForAssignmentNotification
    assigned_user_id: int | None
    role_id: UUID | None = None
    role_member_user_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ErrorTrackingSettings:
    project_rate_limit_value: int | None
    project_rate_limit_bucket_size_minutes: int | None
    per_issue_rate_limit_value: int | None
    per_issue_rate_limit_bucket_size_minutes: int | None
    ingestion_enabled: bool


@dataclass(frozen=True)
class ErrorTrackingSpikeDetectionConfig:
    snooze_duration_minutes: int
    multiplier: int
    threshold: int


@dataclass(frozen=True)
class ErrorTrackingSpikeEventIssue:
    id: UUID
    name: str | None
    description: str | None


@dataclass(frozen=True)
class ErrorTrackingSpikeEvent:
    id: UUID
    issue: ErrorTrackingSpikeEventIssue
    detected_at: datetime
    computed_baseline: float
    current_bucket_value: int


@dataclass(frozen=True)
class ErrorTrackingRelease:
    id: UUID
    hash_id: str
    team_id: int
    created_at: datetime
    metadata: dict | None
    version: str
    project: str


@dataclass(frozen=True)
class ErrorTrackingSymbolSet:
    id: UUID
    ref: str
    team_id: int
    created_at: datetime
    last_used: datetime | None
    failure_reason: str | None
    has_uploaded_file: bool
    release: ErrorTrackingRelease | None


@dataclass(frozen=True)
class ErrorTrackingSymbolSetDownload:
    has_file: bool
    url: str | None


@dataclass(frozen=True)
class ErrorTrackingStackFrame:
    id: UUID
    raw_id: str
    created_at: datetime
    contents: dict
    resolved: bool
    context: dict | None
    symbol_set_ref: str | None
    release: ErrorTrackingRelease | None


@dataclass(frozen=True)
class ErrorTrackingRuleAssignee:
    type: str
    id: int | UUID


@dataclass(frozen=True)
class ErrorTrackingAssignmentRule:
    id: UUID
    filters: dict
    assignee: ErrorTrackingRuleAssignee | None
    order_key: int
    disabled_data: dict | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ErrorTrackingSeverityRule:
    id: UUID
    filters: dict
    severity: Literal["low", "medium", "high", "critical"]
    order_key: int
    disabled_data: dict | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ErrorTrackingGroupingRuleIssue:
    id: UUID
    name: str | None


@dataclass(frozen=True)
class ErrorTrackingGroupingRule:
    id: UUID
    filters: dict
    assignee: ErrorTrackingRuleAssignee | None
    description: str | None
    issue: ErrorTrackingGroupingRuleIssue | None
    order_key: int
    disabled_data: dict | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ErrorTrackingSuppressionRule:
    id: UUID
    filters: dict
    order_key: int
    disabled_data: dict | None
    sampling_rate: float
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ErrorTrackingBuiltInFilter:
    key: str
    name: str
    description: str
    evaluation: BuiltInFilterEvaluation
    enabled: bool
    disabled_reason: str | None


@dataclass(frozen=True)
class ErrorTrackingBypassRule:
    id: UUID
    filters: dict
    order_key: int
    disabled_data: dict | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ErrorTrackingIssueBasics:
    id: UUID
    name: str | None
    description: str | None
    status: str
    severity: str | None
    created_at: datetime
    # Earliest across all fingerprints, merged ones included.
    first_seen: datetime | None


@dataclass(frozen=True)
class ErrorTrackingRecommendation:
    id: UUID
    type: str
    meta: dict
    completed: bool
    status: str
    computed_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SymbolsPlatform(LabeledStrEnum):
    JAVASCRIPT = "javascript", "JavaScript"
    JAVA = "java", "Android"
    NATIVE = "native", "iOS and native"


class MissingSymbolsReason(LabeledStrEnum):
    CHUNK_NOT_UPLOADED = "chunk_not_uploaded", "Source map not uploaded"
    NO_SOURCE_MAP_LINKED = "no_source_map_linked", "Script links no source map"
    FILE_NOT_REACHABLE = "file_not_reachable", "Script or source map not reachable"
    INVALID_SOURCE_MAP = "invalid_source_map", "Source map URL returns something else"
    TOO_LARGE_TO_FETCH = "too_large_to_fetch", "Too large to fetch"
    BUNDLE_NOT_INJECTED = "bundle_not_injected", "Bundle not processed by the PostHog CLI"
    MAPPING_NOT_UPLOADED = "mapping_not_uploaded", "Mapping file not uploaded"
    DSYM_NOT_UPLOADED = "dsym_not_uploaded", "dSYM not uploaded"
    DEBUG_SYMBOLS_NOT_UPLOADED = "debug_symbols_not_uploaded", "Debug symbols not uploaded"


@dataclass(frozen=True)
class MissingSymbolsIssue:
    """An issue whose recent exceptions contain frames from one missing-symbols example."""

    id: UUID
    name: str | None
    description: str | None
    occurrences: int


@dataclass(frozen=True)
class MissingSymbolsStackFrame:
    function: str | None
    source: str | None
    line: int | None
    column: int | None
    in_app: bool
    missing_symbols: bool


@dataclass(frozen=True)
class MissingSymbolsExampleException:
    # The issue page opens this event from the issue ID, the fingerprint and the timestamp.
    issue_id: UUID | None
    fingerprint: str
    timestamp: datetime
    type: str | None
    value: str | None
    # Most recent call first, the order the issue page shows.
    frames: list[MissingSymbolsStackFrame]


@dataclass(frozen=True)
class MissingSymbolsExample:
    """Frames from one file or build that miss the same symbols, for the same reason."""

    reason: MissingSymbolsReason
    location: str | None
    symbol_id: str | None
    http_status: int | None
    frames: int
    # The issues with the most occurrences. `issue_count` counts them all.
    issues: list[MissingSymbolsIssue]
    issue_count: int
    # True when the scan searched only a sample of the frames or stopped at its fingerprint limit,
    # so `issue_count` is a lower bound.
    issue_count_capped: bool
    example_exception: MissingSymbolsExampleException | None


@dataclass(frozen=True)
class MissingSymbolsExamples:
    platform: SymbolsPlatform
    lookback_hours: int
    # False when the exception lookup failed, so the issues and examples are unknown rather than absent.
    exceptions_loaded: bool
    results: list[MissingSymbolsExample]


@dataclass(frozen=True)
class ErrorTrackingAlertDestination:
    id: UUID
    channel_type: str
    integration_id: int | None
    config: dict
    last_delivered_at: datetime | None
    last_failure_at: datetime | None
    last_error: str
    consecutive_failures: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ErrorTrackingAlert:
    id: UUID
    name: str
    enabled: bool
    triggers: list[str]
    filters: dict
    throttle_seconds: int
    destinations: list[ErrorTrackingAlertDestination]
    created_at: datetime
    updated_at: datetime


class IssueSummaryCategory(LabeledStrEnum):
    OWN_CODE = "own_code"
    THIRD_PARTY = "third_party"
    NETWORK = "network"
    BOTS = "bots"
    EXPECTED = "expected"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class ErrorTrackingIssueSummary:
    issue_id: UUID
    what_happened: str
    # A hypothesis, never a finding.
    likely_cause: str
    who_is_affected: str
    suggested_next_step: str
    # None when the category model did not answer.
    category: IssueSummaryCategory | None
    model: str
    generated_at: datetime
    # When the summary was last generated or confirmed unchanged. The 24h regenerate interval runs from it.
    checked_at: datetime
