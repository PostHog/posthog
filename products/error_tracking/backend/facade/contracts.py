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
from uuid import UUID

from pydantic.dataclasses import dataclass


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
    name: str | None
    description: str | None
    first_seen: datetime | None
    assignee: ErrorTrackingIssueAssignee | None


@dataclass(frozen=True)
class ErrorTrackingIssue:
    id: UUID
    status: str
    name: str | None
    description: str | None
    first_seen: datetime | None
    assignee: ErrorTrackingIssueAssignee | None
    external_issues: list[ErrorTrackingExternalReference] = field(default_factory=list)
    cohort: ErrorTrackingIssueCohort | None = None


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
