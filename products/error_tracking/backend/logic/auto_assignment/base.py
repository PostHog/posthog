from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.auto_assignment.gate import AutoAssignmentConfig
from products.error_tracking.backend.logic.issue_changes import AssigneeRef

if TYPE_CHECKING:
    from products.error_tracking.backend.logic.auto_assignment.evidence import IssueEvidence


@frozen
class HistoryEvidence:
    similar_issue_ids: tuple[str, ...]
    nearest_distance: float


type CandidateEvidence = HistoryEvidence


@frozen
class Candidate:
    assignee: AssigneeRef
    confidence: float
    source: str
    reason: str
    evidence: CandidateEvidence


@frozen
class Decision:
    candidate: Candidate
    threshold: float


class Processor(ABC):
    name: str
    # A processor that needs a model to see the issue runs only for organizations that approved AI data processing.
    sends_data_to_model: bool = False

    @abstractmethod
    def threshold(self, config: AutoAssignmentConfig) -> float: ...

    @abstractmethod
    def propose(self, evidence: "IssueEvidence", config: AutoAssignmentConfig) -> Candidate | None:
        """The best assignee this signal can name, or None when it has no evidence.

        Return the best guess even below the threshold, so a backtest can measure other thresholds.
        """
