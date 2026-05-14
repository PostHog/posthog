import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.temporal.constants import MAX_SESSION_ID_LENGTH


class ApplyLensInputs(BaseModel, frozen=True):
    """Input to ApplyLensWorkflow."""

    lens_id: UUID
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    team_id: int
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None = None


class CreateObservationInputs(BaseModel, frozen=True):
    lens_id: UUID
    team_id: int
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None
    workflow_id: str


class CreateObservationOutput(BaseModel, frozen=True):
    """`was_created=False` means the row already existed; the caller should no-op."""

    observation_id: UUID
    was_created: bool


class MarkObservationRunningInputs(BaseModel, frozen=True):
    observation_id: UUID


class MarkObservationFailedInputs(BaseModel, frozen=True):
    observation_id: UUID
    error_reason: str


class FetchSessionEventsInputs(BaseModel, frozen=True):
    observation_id: UUID
    team_id: int
    session_id: str


class LensLlmInputs(BaseModel, frozen=True):
    """Per-session analytics events + recording metadata, stashed in Redis between activities."""

    session_id: str
    team_id: int
    session_start_time: dt.datetime
    session_end_time: dt.datetime
    duration_seconds: float
    columns: list[str]
    events: list[list[Any]]

    @model_validator(mode="after")
    def _events_match_columns(self) -> "LensLlmInputs":
        column_count = len(self.columns)
        for index, row in enumerate(self.events):
            if len(row) != column_count:
                raise ValueError(f"events[{index}] has {len(row)} values but columns has {column_count}")
        return self


class EnsureSessionAssetInputs(BaseModel, frozen=True):
    team_id: int
    session_id: str


class EnsureSessionAssetOutput(BaseModel, frozen=True):
    asset_id: int
