"""Spill files that hold a large source transaction on local disk until its commit arrives.

A change stream only gives a transaction its position at commit, so capture holds every change of it
until then. Holding them on disk instead of in memory makes a bulk change cost worker disk, not worker
memory.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from typing import IO

# Every capture on a worker spills to the same scratch volume, which other warehouse activities also
# use. Open spill files together stay under this share of the volume, so concurrent large
# transactions cannot fill it.
WORKER_SPILL_BUDGET_FRACTION = 0.5


class CDCSpillBudgetExhaustedError(Exception):
    """Other transactions on this worker hold the shared spill budget.

    Retryable: the space frees when those transactions commit or fail.
    """


class WorkerSpillBudget:
    """Bytes held by open spill files across every decoder in this worker process."""

    def __init__(self, limit: int | None = None) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        self._used = 0

    @property
    def limit(self) -> int:
        if self._limit is None:
            self._limit = int(shutil.disk_usage(tempfile.gettempdir()).total * WORKER_SPILL_BUDGET_FRACTION)
        return self._limit

    def reserve(self, size: int) -> bool:
        limit = self.limit
        with self._lock:
            if self._used + size > limit:
                return False
            self._used += size
            return True

    def release(self, size: int) -> None:
        with self._lock:
            self._used -= size


worker_spill_budget = WorkerSpillBudget()


class SpillFile:
    """A transaction's spill file and its share of the worker budget, released together on close."""

    def __init__(self, budget: WorkerSpillBudget) -> None:
        self.file: IO[bytes] = tempfile.TemporaryFile()
        self.bytes = 0
        self._budget = budget

    def write(self, line: bytes) -> bool:
        if not self._budget.reserve(len(line)):
            return False
        # Counted before the write, so close() releases the reservation even when the write fails.
        self.bytes += len(line)
        self.file.write(line)
        return True

    def close(self) -> None:
        self.file.close()
        self._budget.release(self.bytes)
        self.bytes = 0
