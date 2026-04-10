"""Contract types for Error tracking.

Stable, framework-free frozen dataclasses define the public contract surface
for Turbo selective testing. Keep this module limited to stdlib-only contract
shapes that can safely cross product boundaries.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class IssueSummary:
    id: UUID
    team_id: int
    status: str
    name: str | None
    description: str | None
    created_at: datetime


@dataclass(frozen=True)
class ErrorTrackingIssueContract:
    id: str
    team_id: int
    name: str | None
    description: str | None
    status: str


@dataclass(frozen=True)
class ErrorTrackingIssueAssignmentContract:
    id: str
    created_at: datetime
    issue: ErrorTrackingIssueContract
    user_id: int | None
    user_email: str | None
    role_id: str | None
    role_name: str | None


@dataclass(frozen=True)
class ErrorTrackingIssueFingerprintContract:
    id: str
    team_id: int
    issue_id: str
    fingerprint: str
    version: int
    first_seen: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class TeamCountContract:
    team_id: int
    total: int


@dataclass(frozen=True)
class ErrorTrackingWeeklyDigestProjectContract:
    team_id: int
    team_name: str
    exception_count: int
    exception_change: dict | None
    ingestion_failure_count: int
    top_issues: list[dict]
    new_issues: list[dict]
    daily_counts: list[dict]
    crash_free: dict
    error_tracking_url: str
    ingestion_failures_url: str
