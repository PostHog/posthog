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
