import dataclasses

from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import FingerprintEmbeddingResultInputs
from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE = "EmbeddingServiceUnavailable"
SEVERITY_INFERENCE_UNAVAILABLE_ERROR_TYPE = "SeverityInferenceUnavailable"


IssueCreatedSnapshot = LifecycleIssueSnapshot


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
    # "event", "rule" or "heuristic": how cymbal chose `issue.severity`.
    severity_source: str | None = None

    def severity_is_overridable(self) -> bool:
        """A model may only replace a severity that no person chose: the level/handled heuristic, or none.

        A notification without a source can come from a cymbal that predates the field, where
        the severity can be an explicit event value or a rule. Only an empty severity is safe then.
        """
        if self.severity_source is None:
            return self.issue.severity is None
        return self.severity_source == "heuristic"


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
    severity: str | None = None
    skipped_reason: str | None = None


@dataclasses.dataclass(frozen=True)
class IssueCreatedWorkflowResult:
    merged: bool = False
    notified: bool = False
    embedding_skipped_reason: str | None = None
