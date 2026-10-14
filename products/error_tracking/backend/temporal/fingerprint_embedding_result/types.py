import dataclasses

from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot


@dataclasses.dataclass(frozen=True)
class FingerprintEmbeddingResultInputs:
    team_id: int
    fingerprint: str
    rendering: str
    timestamp: str
    model_name: str
    embedding: list[float]
    source_issue_id: str | None = None
    event_uuid: str | None = None
    event_timestamp: str | None = None


@dataclasses.dataclass(frozen=True)
class SimilarFingerprintDistance:
    fingerprint: str
    distance: float


@dataclasses.dataclass(frozen=True)
class AutoMergeReopenedTarget:
    """The merge target that went back to active, with what its reopened notification needs."""

    notification_id: str
    issue_id: str
    issue: LifecycleIssueSnapshot
    assignee: str | None = None


@dataclasses.dataclass(frozen=True)
class AutoMergeOutcome:
    merged_count: int = 0
    reopened_target: AutoMergeReopenedTarget | None = None


@dataclasses.dataclass(frozen=True)
class FingerprintEmbeddingMergeResult:
    merged_count: int = 0
    query_duration_ms: float | None = None
    closest_fingerprints: list[SimilarFingerprintDistance] = dataclasses.field(default_factory=list)
    reopened_target: AutoMergeReopenedTarget | None = None
