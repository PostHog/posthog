"""Issue change rows: the snapshot, the per-kind data payload, and the writer.

Values are raw model values, not display labels: consumers that render messages
map them to labels themselves. Cymbal writes the same JSON shapes from Rust, and
tests/fixtures/issue_change_data.json pins them for both sides.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from django.db.models import Min

import structlog

from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.models.utils import uuid7
from posthog.ph_client import feature_enabled_or_false

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueChange,
    ErrorTrackingIssueFingerprintV2,
)

logger = structlog.get_logger(__name__)

ISSUE_CHANGE_LOG_FLAG = "error-tracking-issue-change-log"

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


def issue_change_log_enabled(team_id: int) -> bool:
    try:
        return feature_enabled_or_false(
            ISSUE_CHANGE_LOG_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        # An unreleased feature stays off when the flags service is unreachable,
        # rather than defaulting on or failing the mutation.
        logger.exception("error_tracking_issue_change_log_flag_check_failed", team_id=team_id)
        return False


@frozen
class ChangeOperation:
    """One user action, ingestion transaction or automation run. Its rows share `operation_id`."""

    id: UUID
    team_id: int
    actor_type: ErrorTrackingIssueChange.ActorType
    actor_user_id: int | None
    bulk: bool

    @classmethod
    def for_user(cls, team_id: int, user: User, *, bulk: bool = False) -> "ChangeOperation | None":
        """Start an operation, or return None when the change log is off for the team.

        Call it before the mutation opens its transaction, so the flag check never holds row locks.
        """
        if not issue_change_log_enabled(team_id):
            return None
        return cls(
            id=uuid7(),
            team_id=team_id,
            actor_type=ErrorTrackingIssueChange.ActorType.USER,
            actor_user_id=user.id,
            bulk=bulk,
        )


@frozen
class IssueChange:
    # The issue as it is after the change. The snapshot is built from it.
    issue: ErrorTrackingIssue
    data: IssueChangeData


def record_issue_changes(operation: ChangeOperation | None, changes: Sequence[IssueChange]) -> None:
    """Write the change rows. Call it inside the transaction that applies the changes."""
    if operation is None or not changes:
        return
    issue_ids = {change.issue.id for change in changes}
    assignees = {
        assignment.issue_id: AssigneeRef.from_assignment(assignment)
        for assignment in ErrorTrackingIssueAssignment.objects.filter(team_id=operation.team_id, issue_id__in=issue_ids)
    }
    first_seen_by_issue: dict[UUID, datetime | None] = dict(
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=operation.team_id, issue_id__in=issue_ids)
        .values("issue_id")
        .annotate(earliest_first_seen=Min("first_seen"))
        .values_list("issue_id", "earliest_first_seen")
    )
    ErrorTrackingIssueChange.objects.for_team(operation.team_id).bulk_create(
        [
            ErrorTrackingIssueChange(
                team_id=operation.team_id,
                issue_id=change.issue.id,
                kind=change.data.kind,
                data=change.data.to_data(),
                snapshot=IssueSnapshot.build(
                    change.issue,
                    assignee=assignees.get(change.issue.id),
                    first_seen=first_seen_by_issue.get(change.issue.id),
                ).to_json(),
                operation_id=operation.id,
                bulk=operation.bulk,
                actor_type=operation.actor_type,
                actor_user_id=operation.actor_user_id,
            )
            for change in changes
        ]
    )
