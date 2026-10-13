"""Per-phase progress of a load batch, from the processor thread to the consumer's watchdog.

The consumer's liveness watchdog sees only how long a batch has been executing. A merge that is
still making progress and a write hung on a dead connection look the same to it until the flat
stuck-batch timeout, which has to be long enough for the largest legitimate merge. This module
records which phase a batch is in and for how long, so the watchdog log, a per-phase gauge and a
per-phase age gauge can tell the two apart in production before any timeout is tightened.

Observe-only: nothing here changes when a batch is judged stuck. The processor reports through
`workload_report.report_phase`, which forwards here for the batch bound to the current context.
"""

from __future__ import annotations

import time
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from prometheus_client import Gauge, Histogram

# Phases the processor reports, in the order a batch normally passes through them. `claimed` is
# the engine's own state before the processor's first report; anything unlisted counts as `other`
# so a new report name cannot mint gauge series without a home here.
KNOWN_PHASES = ("claimed", "deliver", "read", "write", "merge", "post_load", "finalize", "other")

BATCH_PHASE_DURATION_SECONDS = Histogram(
    "warehouse_load_batch_phase_duration_seconds",
    "Wall-clock time a load batch spent in one phase before it moved to the next",
    labelnames=["phase"],
    buckets=(0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)

BATCHES_IN_PHASE = Gauge(
    "warehouse_load_batches_in_phase",
    "Load batches in flight on this process, by the phase they are in now",
    labelnames=["phase"],
    multiprocess_mode="livesum",
)

# A phase that never ends never reaches the histogram, so its age is the only sign of a hang.
BATCH_PHASE_AGE_SECONDS_MAX = Gauge(
    "warehouse_load_batch_phase_age_seconds_max",
    "Longest time any in-flight load batch on this process has spent in its current phase",
    labelnames=["phase"],
    multiprocess_mode="livemax",
)


def _known_phase(phase: str) -> str:
    return phase if phase in KNOWN_PHASES else "other"


@dataclass(frozen=False)
class BatchPhaseProgress:
    """The phase one in-flight batch is in. Written by the processor thread, read by the event loop."""

    phase: str = "claimed"
    phase_started_monotonic: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def advance(self, phase: str) -> None:
        now = time.monotonic()
        with self._lock:
            if phase == self.phase:
                return
            BATCH_PHASE_DURATION_SECONDS.labels(phase=_known_phase(self.phase)).observe(
                now - self.phase_started_monotonic
            )
            self.phase = phase
            self.phase_started_monotonic = now

    def snapshot(self) -> tuple[str, float]:
        """The current phase and the seconds spent in it, read together."""
        with self._lock:
            return self.phase, time.monotonic() - self.phase_started_monotonic


_current_progress: ContextVar[BatchPhaseProgress | None] = ContextVar("dwh_batch_phase_progress", default=None)


def report_batch_phase(phase: str) -> None:
    """Advance the batch bound to the current context; no-op outside one (the import activity)."""
    progress = _current_progress.get()
    if progress is not None:
        progress.advance(phase)


@contextmanager
def track_batch_phases() -> Iterator[BatchPhaseProgress]:
    """Bind a fresh progress record for the batch processed inside the block.

    Contextvars follow `sync_to_async` into the processor thread, so reports made there land on the
    same record the engine holds.
    """
    progress = BatchPhaseProgress()
    token = _current_progress.set(progress)
    try:
        yield progress
    finally:
        _current_progress.reset(token)


def publish_phase_gauges(in_flight: list[BatchPhaseProgress]) -> None:
    """Refresh both gauges from the in-flight records, zeroing phases nothing is in."""
    counts = dict.fromkeys(KNOWN_PHASES, 0)
    oldest = dict.fromkeys(KNOWN_PHASES, 0.0)
    for progress in in_flight:
        phase, seconds = progress.snapshot()
        phase = _known_phase(phase)
        counts[phase] += 1
        oldest[phase] = max(oldest[phase], seconds)
    for phase in KNOWN_PHASES:
        BATCHES_IN_PHASE.labels(phase=phase).set(counts[phase])
        BATCH_PHASE_AGE_SECONDS_MAX.labels(phase=phase).set(oldest[phase])
