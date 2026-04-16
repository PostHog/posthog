"""Transitional contract types for error tracking facade.

These dataclasses are framework-free and represent the facade boundary.
They will move to contracts.py when the product structure migration is complete.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


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
