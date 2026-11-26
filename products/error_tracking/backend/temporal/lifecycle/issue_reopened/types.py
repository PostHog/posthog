import dataclasses

from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

IssueReopenedSnapshot = LifecycleIssueSnapshot


@dataclasses.dataclass(frozen=True)
class IssueReopenedWorkflowInputs:
    notification_id: str
    team_id: int
    issue_id: str
    issue: LifecycleIssueSnapshot
    fingerprint: str
    event_uuid: str
    event_timestamp: str
    assignee: str | None = None
    # The status the exception reopened the issue from. None when the sender predates the field.
    previous_status: str | None = None


@dataclasses.dataclass(frozen=True)
class IssueReopenedWorkflowResult:
    notified: bool = False
