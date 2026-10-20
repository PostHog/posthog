import dataclasses
from datetime import datetime, timedelta

from django.utils.dateparse import parse_datetime

from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

CLOSEST_FINGERPRINTS_WINDOW = timedelta(days=30)


def parse_embedding_timestamp(timestamp: str) -> datetime:
    parsed = parse_datetime(timestamp)
    if parsed is None:
        raise ValueError(f"Invalid embedding timestamp: {timestamp}")
    return parsed


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
    # The text that was embedded, so the judge doesn't read it back before ClickHouse has ingested it.
    content: str | None = None


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
    target_fingerprint: str | None = None
    # Which rule made the merge: "distance" or "judge". None when nothing merged in this attempt.
    merge_decision: str | None = None


@dataclasses.dataclass(frozen=True)
class FingerprintEmbeddingMergeResult:
    merged_count: int = 0
    query_duration_ms: float | None = None
    closest_fingerprints: list[SimilarFingerprintDistance] = dataclasses.field(default_factory=list)
    reopened_target: AutoMergeReopenedTarget | None = None
