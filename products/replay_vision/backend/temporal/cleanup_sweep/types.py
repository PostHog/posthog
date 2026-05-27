"""Input + output dataclasses for the daily Replay Vision cleanup sweep."""

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.cleanup_sweep.constants import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_STRANDED_HOURS,
)


class CleanupSweepInputs(BaseModel, frozen=True):
    retention_days: int = Field(default=DEFAULT_RETENTION_DAYS, ge=1)
    stranded_hours: int = Field(default=DEFAULT_STRANDED_HOURS, ge=1)


class PruneResult(BaseModel, frozen=True):
    rows_deleted: int = 0
    batches_run: int = 0
    hit_cap: bool = False


class ReapResult(BaseModel, frozen=True):
    scanned: int = 0
    reaped: int = 0
    skipped_running: int = 0
    skipped_temporal_error: int = 0
    hit_cap: bool = False


class CleanupSweepResult(BaseModel, frozen=True):
    prune: PruneResult
    reap: ReapResult
