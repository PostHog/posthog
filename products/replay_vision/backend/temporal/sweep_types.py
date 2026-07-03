"""Sweep-only Temporal types — split from `types.py` to avoid a circular import."""

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field

from products.replay_vision.backend.moments import CoalescedMoment
from products.replay_vision.backend.temporal.constants import MAX_SESSION_ID_LENGTH


class SweepScannerInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int


class FindScannerCandidatesInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int
    # Caps how many candidates to fetch this sweep; None uses the default. Set to the in-flight headroom.
    candidate_limit: int | None = None


class CountInFlightAppliesInputs(BaseModel, frozen=True):
    scanner_id: UUID


class CandidateSessionPayload(BaseModel, frozen=True):
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    session_end: dt.datetime
    # Coalesced and capped moments for moments-scoped scanners; empty for recording scope.
    moments: list[CoalescedMoment] = Field(default_factory=list)


class FindScannerCandidatesOutput(BaseModel, frozen=True):
    candidates: list[CandidateSessionPayload]
    saturated: bool


class AdvanceScannerWatermarkInputs(BaseModel, frozen=True):
    scanner_id: UUID
    new_last_swept_at: dt.datetime
    # Empty clears the keyset tiebreaker.
    new_last_seen_session_id: str = Field(max_length=MAX_SESSION_ID_LENGTH)
