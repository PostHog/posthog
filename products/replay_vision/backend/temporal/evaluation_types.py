from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.constants import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.temporal.types import ScannerSnapshot


class EvaluatePromptSuggestionInputs(BaseModel, frozen=True):
    suggestion_id: UUID
    team_id: int
    # How many rated sessions to re-run. None means the cap. Can lower the cap, never raise it.
    session_limit: int | None = None
    # The edited config the user is testing. None re-runs the stored suggested_config. Defaulted so an
    # in-flight run replaying without this field decodes it as "test the suggestion" (its original behavior).
    config_override: dict[str, Any] | None = None


class EvaluationSession(BaseModel, frozen=True):
    """One rated session to re-run with the suggested prompt."""

    observation_id: UUID
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    rated_correct: bool
    before_outcome: str | None


class SelectEvaluationSessionsInputs(BaseModel, frozen=True):
    suggestion_id: UUID
    team_id: int
    session_limit: int | None = None
    config_override: dict[str, Any] | None = None


class SelectEvaluationSessionsOutput(BaseModel, frozen=True):
    sessions: list[EvaluationSession]
    # Current scanner state with the suggested prompt swapped in, exactly what applying would produce.
    snapshot: ScannerSnapshot | None = None


class RecordEvaluationResultInputs(BaseModel, frozen=True):
    suggestion_id: UUID
    team_id: int
    session: EvaluationSession
    # Model that ran the re-run, frozen from the evaluation snapshot; prices the usage receipt.
    model: str | None = None
    # The fresh scanner output, None when the run errored.
    after_output: dict[str, Any] | None = None
    error: str | None = None
    # Defaulted to False so an in-flight run replaying without this field decodes it as a non-preview run.
    preview: bool = False


class FinalizeEvaluationInputs(BaseModel, frozen=True):
    suggestion_id: UUID
    team_id: int
    failed: bool = False
