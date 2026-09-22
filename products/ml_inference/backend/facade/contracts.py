"""
Contract types for ml_inference: the decision request a caller builds and the answers it gets back.

Uses ``pydantic.dataclasses.dataclass`` so a malformed gateway answer fails at construction rather than deep in a caller.
"""

from pydantic.dataclasses import dataclass

from .enums import DecisionQuestionType

DEFAULT_DECISION_MODEL = "posthog/posthog/decision-4b"


class DecisionsDisabledError(Exception):
    """The team is not enrolled in decisions; callers show the feature as absent."""

    def __init__(self, team_id: int) -> None:
        super().__init__(f"decisions are not enabled for team {team_id}")
        self.team_id = team_id


class DecisionGatewayError(Exception):
    """The gateway answered, but not with a decision."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"decision gateway returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DecisionQuestion:
    type: DecisionQuestionType
    instructions: str
    criteria: dict[str, str] | None = None


@dataclass(frozen=True)
class DecisionRequest:
    team_id: int
    state: str
    questions: dict[str, DecisionQuestion]
    model: str = DEFAULT_DECISION_MODEL


@dataclass(frozen=True)
class NoulAnswer:
    probability: float


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    confidence: float
    probabilities: dict[str, float]


DecisionAnswer = NoulAnswer | ChoiceAnswer | ScoreAnswer


@dataclass(frozen=True)
class DecisionResult:
    model: str
    answers: dict[str, DecisionAnswer]
    input_tokens: int
    latency_ms: int | None = None
