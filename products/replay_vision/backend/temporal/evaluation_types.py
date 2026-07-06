from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.constants import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.temporal.types import ScannerSnapshot


class EvaluatePromptSuggestionInputs(BaseModel, frozen=True):
    """Input to EvaluatePromptSuggestionWorkflow."""

    suggestion_id: UUID
    team_id: int


class EvaluationSession(BaseModel, frozen=True):
    """One rated session to re-run with the suggested prompt."""

    observation_id: UUID
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    rated_correct: bool
    before_outcome: str | None


class SelectEvaluationSessionsInputs(BaseModel, frozen=True):
    suggestion_id: UUID
    team_id: int


class SelectEvaluationSessionsOutput(BaseModel, frozen=True):
    sessions: list[EvaluationSession]
    # Current scanner state with the suggested scanner_config swapped in, exactly what applying would produce.
    snapshot: ScannerSnapshot | None = None


class RecordEvaluationResultInputs(BaseModel, frozen=True):
    suggestion_id: UUID
    team_id: int
    session: EvaluationSession
    # The fresh scanner output, None when the run errored.
    after_output: dict[str, Any] | None = None
    error: str | None = None


class FinalizeEvaluationInputs(BaseModel, frozen=True):
    suggestion_id: UUID
    team_id: int
    failed: bool = False
