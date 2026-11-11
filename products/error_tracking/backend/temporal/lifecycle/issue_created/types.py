import dataclasses
from enum import StrEnum

from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import FingerprintEmbeddingResultInputs
from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE = "EmbeddingServiceUnavailable"
SEVERITY_INFERENCE_UNAVAILABLE_ERROR_TYPE = "SeverityInferenceUnavailable"


IssueCreatedSnapshot = LifecycleIssueSnapshot


class SeveritySource(StrEnum):
    """How cymbal chose the severity of a new issue. Mirrors `SeveritySource` in cymbal's notification.rs.

    Temporal rejects an input with an unknown value, so add a value here before cymbal sends it.
    """

    EVENT = "event"
    RULE = "rule"
    HEURISTIC = "heuristic"


class SeverityInferenceSkipReason(StrEnum):
    DISABLED = "disabled"
    TEAM_MISSING = "team_missing"
    AI_DATA_PROCESSING_NOT_APPROVED = "ai_data_processing_not_approved"
    NO_EXCEPTION = "no_exception"
    DECISIONS_UNAVAILABLE = "decisions_unavailable"
    GATEWAY_REJECTED = "gateway_rejected"
    UNEXPECTED_ANSWER = "unexpected_answer"
    SEVERITY_CHANGED = "severity_changed"


@dataclasses.dataclass(frozen=True)
class IssueCreatedWorkflowInputs:
    notification_id: str
    team_id: int
    issue_id: str
    issue: LifecycleIssueSnapshot
    fingerprint: str
    event_uuid: str
    event_timestamp: str
    assignee: str | None = None
    severity_source: SeveritySource | None = None

    def severity_is_overridable(self) -> bool:
        """A model may only replace a severity that no person chose: the level/handled heuristic, or none.

        A notification without a source can come from a cymbal that predates the field, where
        the severity can be an explicit event value or a rule. Only an empty severity is safe then.
        """
        if self.severity_source is None:
            return self.issue.severity is None
        return self.severity_source == SeveritySource.HEURISTIC


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
class IssueSeverityInferenceResult:
    # True when inference read the issue row. Downstream side effects must then carry `stored_severity`.
    resolved: bool = False
    stored_severity: str | None = None
    skipped_reason: SeverityInferenceSkipReason | None = None


@dataclasses.dataclass(frozen=True)
class IssueCreatedWorkflowResult:
    merged: bool = False
    notified: bool = False
    embedding_skipped_reason: str | None = None
