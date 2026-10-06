"""Typed contents of issue change rows: the snapshot and the per-kind data payload.

Values are raw model values, not display labels: consumers that render messages
map them to labels themselves. Cymbal writes the same JSON shapes from Rust, and
tests/fixtures/issue_change_data.json pins them for both sides.
"""

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from posthog.dataclasses import frozen

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueChange,
)

Kind = ErrorTrackingIssueChange.Kind
Status = ErrorTrackingIssue.Status
Severity = ErrorTrackingIssue.Severity

# Same cap the alert delivery inputs apply, so a long exception message cannot bloat every row.
MAX_ISSUE_NAME_LENGTH = 500


def _truncate_name(name: str | None) -> str | None:
    return name[:MAX_ISSUE_NAME_LENGTH] if name else name


@frozen
class AssigneeRef:
    type: Literal["user", "role"]
    id: str

    @classmethod
    def from_assignment(cls, assignment: ErrorTrackingIssueAssignment | None) -> "AssigneeRef | None":
        if assignment is None:
            return None
        if assignment.user_id is not None:
            return cls(type="user", id=str(assignment.user_id))
        if assignment.role_id is not None:
            return cls(type="role", id=str(assignment.role_id))
        return None

    @classmethod
    def from_json(cls, value: dict[str, Any] | None) -> "AssigneeRef | None":
        if value is None:
            return None
        if value["type"] not in ("user", "role"):
            raise ValueError(f"Unknown assignee type: {value['type']}")
        return cls(type=value["type"], id=str(value["id"]))

    def to_json(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}


@frozen
class IssueSnapshot:
    status: Status
    severity: Severity | None
    name: str | None
    assignee: AssigneeRef | None
    first_seen: datetime

    @classmethod
    def build(
        cls, issue: ErrorTrackingIssue, *, assignee: AssigneeRef | None, first_seen: datetime | None
    ) -> "IssueSnapshot":
        """Build the snapshot after a change.

        The caller loads the assignee and the earliest fingerprint `first_seen`
        (`ErrorTrackingIssue.objects.with_first_seen()`), so a bulk change needs one query
        for each instead of one per issue. After a merge, the earliest fingerprint can
        predate the issue row, so `created_at` is only the fallback.
        """
        return cls(
            status=Status(issue.status),
            severity=Severity(issue.severity) if issue.severity else None,
            name=_truncate_name(issue.name),
            assignee=assignee,
            first_seen=first_seen or issue.created_at,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "severity": str(self.severity) if self.severity else None,
            "name": self.name,
            "assignee": self.assignee.to_json() if self.assignee else None,
            "first_seen": self.first_seen.isoformat(),
        }


@frozen
class Created:
    kind: ClassVar[Kind] = Kind.CREATED

    def to_data(self) -> dict[str, Any]:
        return {}


@frozen
class StatusChanged:
    kind: ClassVar[Kind] = Kind.STATUS_CHANGED
    previous: Status

    def to_data(self) -> dict[str, Any]:
        return {"previous": str(self.previous)}


@frozen
class AssigneeChanged:
    kind: ClassVar[Kind] = Kind.ASSIGNEE_CHANGED
    previous: AssigneeRef | None

    def to_data(self) -> dict[str, Any]:
        return {"previous": self.previous.to_json() if self.previous else None}


@frozen
class SeverityChanged:
    kind: ClassVar[Kind] = Kind.SEVERITY_CHANGED
    previous: Severity | None

    def to_data(self) -> dict[str, Any]:
        return {"previous": str(self.previous) if self.previous else None}


@frozen
class NameChanged:
    kind: ClassVar[Kind] = Kind.NAME_CHANGED
    previous: str | None

    def to_data(self) -> dict[str, Any]:
        return {"previous": _truncate_name(self.previous)}


@frozen
class Merged:
    """Written on the target issue. The merged issues are deleted, so they get no row."""

    kind: ClassVar[Kind] = Kind.MERGED
    merged_issue_ids: tuple[UUID, ...]

    def to_data(self) -> dict[str, Any]:
        return {"merged_issue_ids": [str(issue_id) for issue_id in self.merged_issue_ids]}


@frozen
class Split:
    """Written on the original issue. Each new issue also gets a `created` row."""

    kind: ClassVar[Kind] = Kind.SPLIT
    new_issue_ids: tuple[UUID, ...]

    def to_data(self) -> dict[str, Any]:
        return {"new_issue_ids": [str(issue_id) for issue_id in self.new_issue_ids]}


@frozen
class Spiking:
    kind: ClassVar[Kind] = Kind.SPIKING
    computed_baseline: float
    current_bucket_value: int

    def to_data(self) -> dict[str, Any]:
        return {"computed_baseline": self.computed_baseline, "current_bucket_value": self.current_bucket_value}


IssueChangeData = Created | StatusChanged | AssigneeChanged | SeverityChanged | NameChanged | Merged | Split | Spiking


def parse_change_data(kind: str, data: dict[str, Any]) -> IssueChangeData:
    match Kind(kind):
        case Kind.CREATED:
            return Created()
        case Kind.STATUS_CHANGED:
            return StatusChanged(previous=Status(data["previous"]))
        case Kind.ASSIGNEE_CHANGED:
            return AssigneeChanged(previous=AssigneeRef.from_json(data["previous"]))
        case Kind.SEVERITY_CHANGED:
            return SeverityChanged(previous=Severity(data["previous"]) if data["previous"] else None)
        case Kind.NAME_CHANGED:
            return NameChanged(previous=data["previous"])
        case Kind.MERGED:
            return Merged(merged_issue_ids=tuple(UUID(issue_id) for issue_id in data["merged_issue_ids"]))
        case Kind.SPLIT:
            return Split(new_issue_ids=tuple(UUID(issue_id) for issue_id in data["new_issue_ids"]))
        case Kind.SPIKING:
            return Spiking(
                computed_baseline=float(data["computed_baseline"]),
                current_bucket_value=int(data["current_bucket_value"]),
            )
    # Unreachable while every kind has a case above. It turns a kind added without one into an error.
    raise ValueError(f"Unhandled issue change kind: {kind}")
