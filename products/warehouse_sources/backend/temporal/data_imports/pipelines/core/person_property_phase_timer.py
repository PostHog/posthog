"""Wall-clock time per phase of a person-property sync or backfill run.

A run's time splits into reading rows, building bundles, diffing against the snapshot, looking up
which entities exist, producing to Kafka, and writing the snapshot. Each timed call feeds one
histogram, and the timer keeps per-batch and per-run totals for the structured log lines, so a slow
run shows which phase it spent its time in.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from prometheus_client import Histogram

RunMode = Literal["backfill", "incremental"]

Phase = Literal[
    # Backfill only: the first pass over the table that finds each repeated distinct_id's last row.
    "read_key_pass",
    "read",
    "bundle_build",
    "snapshot_read",
    "diff",
    "existence_lookup",
    "produce",
    "snapshot_write",
    "progress_record",
    "compaction",
]

# No team, source or binding label: one series per table would grow without bound on a long-lived
# worker. Those identify a run on its log lines instead.
PERSON_PROPERTY_PHASE_DURATION_SECONDS = Histogram(
    "warehouse_person_property_phase_duration_seconds",
    "Duration of one timed call within a person-property sync or backfill, by run mode and phase",
    labelnames=["mode", "phase"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)


class PhaseTimer:
    """Not thread-safe. The run awaits each phase before the next starts, so a phase that runs in a
    worker thread never overlaps another."""

    def __init__(self, mode: RunMode) -> None:
        self.mode: RunMode = mode
        self._started = time.perf_counter()
        self._batch: dict[str, float] = {}
        self._run: dict[str, float] = {}

    @contextmanager
    def phase(self, name: Phase) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, time.perf_counter() - started)

    def add(self, name: Phase, seconds: float) -> None:
        self._batch[name] = self._batch.get(name, 0.0) + seconds
        self._run[name] = self._run.get(name, 0.0) + seconds
        PERSON_PROPERTY_PHASE_DURATION_SECONDS.labels(mode=self.mode, phase=name).observe(seconds)

    def take_batch_fields(self) -> dict[str, int]:
        """The ``<phase>_ms`` fields for the phases timed since the previous call, then starts a new batch."""
        fields = _ms_fields(self._batch)
        self._batch = {}
        return fields

    def run_fields(self) -> dict[str, int]:
        """The ``<phase>_ms`` totals for the whole run, plus its wall time and the part no phase covers."""
        total = time.perf_counter() - self._started
        return {
            **_ms_fields(self._run),
            "total_ms": round(total * 1000),
            "untimed_ms": round(max(total - sum(self._run.values()), 0.0) * 1000),
        }


def _ms_fields(seconds_by_phase: dict[str, float]) -> dict[str, int]:
    return {f"{name}_ms": round(seconds * 1000) for name, seconds in seconds_by_phase.items()}
