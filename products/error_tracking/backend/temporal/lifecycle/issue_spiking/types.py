import dataclasses

from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot, SpikeEventPersistenceStatus

IssueSpikingSnapshot = LifecycleIssueSnapshot


@dataclasses.dataclass(frozen=True)
class IssueSpikingWorkflowInputs:
    notification_id: str
    team_id: int
    issue_id: str
    issue: LifecycleIssueSnapshot
    fingerprint: str
    event_uuid: str
    event_timestamp: str
    detected_at: str
    computed_baseline: float
    current_bucket_value: float
    assignee: str | None = None


@dataclasses.dataclass(frozen=True)
class SpikeEventPersistenceResult:
    status: SpikeEventPersistenceStatus


@dataclasses.dataclass(frozen=True)
class IssueSpikingWorkflowResult:
    persisted: bool = False
    notified: bool = False
