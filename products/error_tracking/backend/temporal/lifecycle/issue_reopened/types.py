import dataclasses
from enum import StrEnum

from posthog.dataclasses import frozen

from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

IssueReopenedSnapshot = LifecycleIssueSnapshot


class IssueReopenReason(StrEnum):
    NEW_RELEASE = "new_release"
    NEW_OCCURRENCE = "new_occurrence"


@frozen
class ReopenedByRelease:
    id: str
    version: str
    project: str
    created_at: str


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
    # Set only when the exception came from a release newer than the latest release the issue was seen in.
    reopened_by_release: ReopenedByRelease | None = None

    @property
    def reopen_reason(self) -> IssueReopenReason:
        if self.reopened_by_release is None:
            return IssueReopenReason.NEW_OCCURRENCE
        return IssueReopenReason.NEW_RELEASE


@dataclasses.dataclass(frozen=True)
class IssueReopenedWorkflowResult:
    notified: bool = False
