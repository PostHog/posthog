from uuid import UUID

from pydantic import BaseModel


class ExperimentSynthesisInputs(BaseModel, frozen=True):
    """Every step reads and writes the synthesis row, so only its id crosses the Temporal boundary."""

    synthesis_id: UUID
    team_id: int


class FailExperimentSynthesisInputs(BaseModel, frozen=True):
    synthesis_id: UUID
    team_id: int
    error: str


class RefreshExperimentSynthesisInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int


class RefreshExperimentSynthesisOutput(BaseModel, frozen=True):
    # The run the sweep should start, claimed by the activity; None when no refresh is due.
    synthesis_id: UUID | None = None
