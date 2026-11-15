"""Resume cursors at a boundary, for a source that batches rows in a local `Batcher`.

Such a source reaches the end of a page, window or parent with rows still in its batcher. A cursor
saved there says "continue after this boundary", so a resume from it does not read those rows again.
The cursor is correct only when the batcher is empty, or when the rows go to the pipeline together
with it.

Each table that a resumable source yields is written as one batch, so a flush at every boundary
makes many small batches. `BoundaryCheckpoint` therefore flushes a partly filled batcher at most
once per interval, and saves no cursor for the boundaries between two flushes. The cursor is then
late, which only makes a resume read more rows again.
"""

import time
from collections.abc import Callable, Iterator
from typing import Generic

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ResumableData

PARTIAL_FLUSH_INTERVAL_SECONDS = 60.0


class BoundaryCheckpoint(Generic[ResumableData]):
    def __init__(
        self,
        batcher: Batcher,
        manager: ResumableSourceManager[ResumableData],
        *,
        flush_interval_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._batcher = batcher
        self._manager = manager
        self._flush_interval_seconds = (
            PARTIAL_FLUSH_INTERVAL_SECONDS if flush_interval_seconds is None else flush_interval_seconds
        )
        self._clock = clock
        self._last_flush = clock()

    def save(self, state: ResumableData) -> Iterator[pa.Table]:
        """Save `state` at a boundary. Use it as `yield from checkpoint.save(state)`.

        Call it only where `state` covers every row the source has read, and the batcher is the only
        place that can still hold some of them.
        """
        if not self._batcher.should_yield(include_incomplete_chunk=True):
            self._manager.save_state(state)
            # Nothing is buffered, so a run of boundaries with no rows keeps its progress.
            self._manager.safe_point()
            return
        if self._clock() - self._last_flush < self._flush_interval_seconds:
            return
        # Saved before the yield, so the pipeline receives the rows and their cursor together.
        self._manager.save_state(state)
        yield self._batcher.get_table()
        self._last_flush = self._clock()
