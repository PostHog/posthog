import dataclasses

from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import FingerprintEmbeddingResultInputs

EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE = "EmbeddingServiceUnavailable"


@dataclasses.dataclass(frozen=True)
class IssueCreatedSnapshot:
    name: str | None
    description: str | None
    status: str
    created_at: str


@dataclasses.dataclass(frozen=True)
class IssueCreatedWorkflowInputs:
    notification_id: str
    team_id: int
    issue_id: str
    issue: IssueCreatedSnapshot
    fingerprint: str
    event_uuid: str
    event_timestamp: str
    assignee: str | None = None


@dataclasses.dataclass(frozen=True)
class GeneratedIssueEmbedding:
    merge_inputs: FingerprintEmbeddingResultInputs
    content: str


@dataclasses.dataclass(frozen=True)
class IssueEmbeddingPreparationResult:
    team_exists: bool
    embedding: GeneratedIssueEmbedding | None = None
    skipped_reason: str | None = None


@dataclasses.dataclass(frozen=True)
class IssueCreatedWorkflowResult:
    merged: bool = False
    notified: bool = False
    embedding_skipped_reason: str | None = None
