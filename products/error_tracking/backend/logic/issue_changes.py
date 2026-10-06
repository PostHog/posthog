"""Snapshots of the watched issue fields, stored on each issue change row.

Values are raw model values, not display labels: consumers that render messages
map them to labels themselves.
"""

from datetime import datetime
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment

# Same cap the alert delivery inputs apply, so a long exception message cannot bloat every row.
MAX_SNAPSHOT_NAME_LENGTH = 500


@frozen
class SnapshotAssignee:
    type: Literal["user", "role"]
    id: str

    @classmethod
    def from_assignment(cls, assignment: ErrorTrackingIssueAssignment | None) -> "SnapshotAssignee | None":
        if assignment is None:
            return None
        if assignment.user_id is not None:
            return cls(type="user", id=str(assignment.user_id))
        if assignment.role_id is not None:
            return cls(type="role", id=str(assignment.role_id))
        return None


@frozen
class IssueSnapshot:
    status: str
    severity: str | None
    name: str | None
    assignee: SnapshotAssignee | None
    first_seen: datetime

    @classmethod
    def build(cls, issue: ErrorTrackingIssue, assignee: SnapshotAssignee | None) -> "IssueSnapshot":
        # The caller passes the assignee so that a bulk change can load all assignments in one query.
        name = issue.name[:MAX_SNAPSHOT_NAME_LENGTH] if issue.name else issue.name
        return cls(
            status=issue.status,
            severity=issue.severity,
            name=name,
            assignee=assignee,
            first_seen=issue.created_at,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "severity": self.severity,
            "name": self.name,
            "assignee": {"type": self.assignee.type, "id": self.assignee.id} if self.assignee else None,
            "first_seen": self.first_seen.isoformat(),
        }
