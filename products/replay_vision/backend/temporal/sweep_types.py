"""Sweep-only Temporal types — split from `types.py` to avoid a circular import."""

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field

from products.replay_vision.backend.session_limits import MAX_SESSION_ID_LENGTH


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
    team_id: int


class InFlightApplyCounts(BaseModel, frozen=True):
    scanner: int
    team: int


class CandidateSessionPayload(BaseModel, frozen=True):
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    session_end: dt.datetime


class FindScannerCandidatesOutput(BaseModel, frozen=True):
    candidates: list[CandidateSessionPayload]
    saturated: bool
    # Settle horizon the query covered; None on short-circuit paths, which skips the empty-sweep advance.
    swept_through: dt.datetime | None = None
    # Stragglers from the periodic full-events-lookback catch-up pass; dispatch-only, never drive
    # the fast watermark.
    deep_candidates: list[CandidateSessionPayload] = Field(default_factory=list)
    # Keyset tiebreaker the deep pass stopped on; empty when it finished its window.
    deep_keyset_session_id: str = ""
    # Horizon the deep pass covered; None when it didn't run.
    deep_swept_through: dt.datetime | None = None
    # One-off priming pass for a never-swept scanner; dispatch-only, never drives any watermark.
    priming_candidates: list[CandidateSessionPayload] = Field(default_factory=list)
    # Last row of the fetched batch, before negative-filter exclusion dropped any of it. Dropping rows
    # must not regress or stall the keyset. None on empty batches, where the workflow falls back to
    # `swept_through`.
    keyset_end: dt.datetime | None = None
    keyset_session_id: str = ""
    # The balanced per-variant rates this tick's candidates were sampled at (experiment scanners
    # with balancing on; None otherwise). Recorded onto each
    # observation's snapshot, so even per-variant counts don't read as even traffic.
    variant_sampling_rates: dict[str, float] | None = None


class CheckScannerBudgetInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int


class CheckScannerBudgetOutput(BaseModel, frozen=True):
    capped: bool = False


class AdvanceScannerWatermarkInputs(BaseModel, frozen=True):
    scanner_id: UUID
    new_last_swept_at: dt.datetime
    # Empty clears the keyset tiebreaker.
    new_last_seen_session_id: str = Field(max_length=MAX_SESSION_ID_LENGTH)
    # None leaves the deep-sweep watermark untouched.
    new_last_deep_swept_at: dt.datetime | None = None
    # Only read when the deep watermark moves; empty clears the deep keyset tiebreaker.
    new_last_deep_seen_session_id: str = ""


class SweepScannerTickOutput(BaseModel, frozen=True):
    # None when the tick already finished inside the activity: gated, or nothing to dispatch.
    dispatch: FindScannerCandidatesOutput | None = None


def watermark_advance(scanner_id: UUID, found: FindScannerCandidatesOutput) -> AdvanceScannerWatermarkInputs | None:
    if found.keyset_end is not None:
        # The fetched batch's last row, which sits ahead of the dispatched candidates whenever
        # exclusion dropped some, so dropping rows cannot stall the walk.
        swept_at = found.keyset_end
        # Always carried: the keyset compares the whole tuple, so keeping the tiebreaker cannot
        # skip anything, while dropping it hides any session tied at that exact end_time.
        last_seen_session_id = found.keyset_session_id
    elif found.swept_through is not None:
        # Advance through the covered settle horizon so `last_swept_at` reflects sweep liveness
        # instead of freezing on low-yield scanners.
        swept_at, last_seen_session_id = found.swept_through, ""
    else:
        return None
    return AdvanceScannerWatermarkInputs(
        scanner_id=scanner_id,
        new_last_swept_at=swept_at,
        new_last_seen_session_id=last_seen_session_id,
        new_last_deep_swept_at=found.deep_swept_through,
        new_last_deep_seen_session_id=found.deep_keyset_session_id,
    )
