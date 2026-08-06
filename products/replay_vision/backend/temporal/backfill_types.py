"""Backfill-only Temporal types — split from `types.py` for the same reason as `sweep_types.py`."""

import enum
import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.constants import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.temporal.sweep_types import CandidateSessionPayload


class BackfillTickInputs(BaseModel, frozen=True):
    backfill_id: UUID
    team_id: int
    # Immutable for a backfill's lifetime, so safe to bake into the schedule action.
    scanner_id: UUID


class BackfillTickAction(enum.StrEnum):
    # Dispatch a batch bounded by `dispatch_budget`.
    DISPATCH = "dispatch"
    # Nothing to do this tick (no headroom, or the scanner is disabled); try again next fire.
    SKIP = "skip"
    # Org quota exhausted: the row is now paused_quota; the workflow pauses the schedule and exits.
    PAUSE = "pause"
    # Terminal row (completed/cancelled/missing): the workflow deletes the schedule and exits.
    FINISHED = "finished"


class PrepareBackfillTickOutput(BaseModel, frozen=True):
    action: BackfillTickAction
    dispatch_budget: int = 0


class FindBackfillCandidatesInputs(BaseModel, frozen=True):
    backfill_id: UUID
    team_id: int
    candidate_limit: int


class FindBackfillCandidatesOutput(BaseModel, frozen=True):
    candidates: list[CandidateSessionPayload]
    # A full batch means there may be more below the keyset; anything less means the walk reached the window start.
    saturated: bool


class AdvanceBackfillCursorInputs(BaseModel, frozen=True):
    backfill_id: UUID
    team_id: int
    # None leaves the cursor untouched (the empty-batch completion path).
    new_cursor_end_time: dt.datetime | None = None
    new_cursor_session_id: str = Field(default="", max_length=MAX_SESSION_ID_LENGTH)
    dispatched_delta: int = 0
    # True when the batch came back short: the window is fully walked and the backfill completes.
    exhausted: bool


class AdvanceBackfillCursorOutput(BaseModel, frozen=True):
    finished: bool


class BackfillScheduleOpInputs(BaseModel, frozen=True):
    backfill_id: UUID
