"""Backfill-only Temporal types — split from `types.py` for the same reason as `sweep_types.py`."""

import enum
import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field

from products.replay_vision.backend.session_limits import MAX_SESSION_ID_LENGTH
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
    # Where the walk got to, which is not always the last dispatched session: sessions this scanner
    # already observed are stepped over without dispatching, while sessions held back by the caps
    # must stay above the cursor so a later tick retries them. None leaves the cursor untouched.
    next_cursor_end_time: dt.datetime | None = None
    next_cursor_session_id: str = Field(default="", max_length=MAX_SESSION_ID_LENGTH)
    # Cursor the walk started from, threaded into the advance so it can match on it.
    started_from_cursor_end_time: dt.datetime | None = None
    started_from_cursor_session_id: str = Field(default="", max_length=MAX_SESSION_ID_LENGTH)
    # Candidates the walk stepped over as already tried. Defaults to 0 so replays of pre-change
    # histories decode, and they simply do not credit the skips.
    skipped_delta: int = 0
    # False only when the walk genuinely reached the window start: a batch the caps truncated still
    # has work below the cursor. The tick completes the backfill exactly when this is False.
    more_work_below_cursor: bool


class AdvanceBackfillCursorInputs(BaseModel, frozen=True):
    backfill_id: UUID
    team_id: int
    # Cursor this tick started from. The update matches on it, so a retry after a committed-but-lost
    # attempt matches nothing and cannot double-count `dispatched_count`.
    expected_cursor_end_time: dt.datetime | None = None
    expected_cursor_session_id: str = Field(default="", max_length=MAX_SESSION_ID_LENGTH)
    # None leaves the cursor untouched (the empty-batch completion path).
    new_cursor_end_time: dt.datetime | None = None
    new_cursor_session_id: str = Field(default="", max_length=MAX_SESSION_ID_LENGTH)
    dispatched_delta: int = 0
    skipped_delta: int = 0
    # True when the batch came back short: the window is fully walked and the backfill completes.
    exhausted: bool


class AdvanceBackfillCursorOutput(BaseModel, frozen=True):
    finished: bool


class BackfillScheduleOpInputs(BaseModel, frozen=True):
    backfill_id: UUID
