"""
Contract types for ml_inference: the decision request a caller builds and the answers it gets back.

Uses ``pydantic.dataclasses.dataclass`` so a malformed gateway answer fails at construction rather than deep in a caller.
"""

from pydantic.dataclasses import dataclass

from .enums import DecisionQuestionType

DEFAULT_DECISION_MODEL = "posthog/hogference/jevk5-bf16-0.3"

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


class DecisionsDisabledError(Exception):
    """The team is not enrolled in decisions; callers show the feature as absent."""

    def __init__(self, team_id: int) -> None:
        super().__init__(f"decisions are not enabled for team {team_id}")
        self.team_id = team_id


class DecisionGatewayUnreachableError(Exception):
    """The gateway did not answer at all: a timeout, a refused connection, a DNS failure."""


class DecisionGatewayError(Exception):
    """The gateway answered, but not with a decision."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"decision gateway returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


MAX_QUESTIONS_PER_REQUEST = 32
# JevK5 answers with one letter per option, A to P.
MAX_OPTIONS_PER_QUESTION = 16


@dataclass(frozen=True)
class DecisionQuestion:
    type: DecisionQuestionType
    instructions: str
    criteria: dict[str, str] | list[str] | None = None

    def __post_init__(self) -> None:
        if self.type == DecisionQuestionType.SCORE and not (
            isinstance(self.criteria, list) and len(self.criteria) >= 2
        ):
            raise ValueError("a score question needs a list of at least two scale labels as criteria")
        if self.type == DecisionQuestionType.CHOICE and not (isinstance(self.criteria, dict) and self.criteria):
            raise ValueError("a choice question needs its options as criteria, keyed by name")
        if self.type == DecisionQuestionType.NOUL and isinstance(self.criteria, list):
            raise ValueError("a yes/no question takes criteria keyed by name, not a list")
        if self.criteria is not None and len(self.criteria) > MAX_OPTIONS_PER_QUESTION:
            raise ValueError(f"a question takes at most {MAX_OPTIONS_PER_QUESTION} options")


@dataclass(frozen=True)
class DecisionRequest:
    team_id: int
    state: JsonValue
    questions: dict[str, DecisionQuestion]
    model: str = DEFAULT_DECISION_MODEL
    ai_product: str = "ml_inference"
    trace_id: str | None = None
    properties: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if len(self.questions) > MAX_QUESTIONS_PER_REQUEST:
            raise ValueError(f"a request takes at most {MAX_QUESTIONS_PER_REQUEST} questions")


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
    latency_ms: float | None = None
