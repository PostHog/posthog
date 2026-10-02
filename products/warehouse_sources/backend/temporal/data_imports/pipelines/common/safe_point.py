import time
from collections.abc import Callable
from typing import Any

from posthog.temporal.common.shutdown import ShutdownMonitor

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# A source can reach a safe point on every request, so the cursor commit it allows is rate-limited.
# The value bounds how much empty-page progress an OOM or SIGKILL can lose.
SAFE_POINT_COMMIT_INTERVAL_SECONDS = 30.0


class PipelineSafePointHandler:
    """The hook a pipeline installs for a resumable source's safe points (see `sources/common/safe_point.py`).

    It runs in the source's thread while the pipeline waits for the next item, so the pipeline's own
    state (the batcher, held queue rows) is not changing under it.
    """

    def __init__(
        self,
        *,
        shutdown_monitor: ShutdownMonitor,
        resumable_source_manager: ResumableSourceManager[Any],
        has_unwritten_rows: Callable[[], bool],
        commit_interval_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._shutdown_monitor = shutdown_monitor
        self._resumable_source_manager = resumable_source_manager
        self._has_unwritten_rows = has_unwritten_rows
        self._commit_interval_seconds = (
            SAFE_POINT_COMMIT_INTERVAL_SECONDS if commit_interval_seconds is None else commit_interval_seconds
        )
        self._clock = clock
        self._last_commit = clock()

    def __call__(self) -> None:
        # The pipeline's `except` path writes the rows it holds and then commits the staged cursor,
        # so a raise here hands the run to another worker without losing progress.
        self._shutdown_monitor.raise_if_is_worker_shutdown()

        now = self._clock()
        if now - self._last_commit < self._commit_interval_seconds:
            return
        # A cursor may commit only once the rows it covers are written. With rows still buffered or a
        # batch still held, the next write commits it instead.
        if self._has_unwritten_rows() or not self._resumable_source_manager.has_staged_state():
            return
        self._resumable_source_manager.commit()
        self._last_commit = now


def source_items_are_framework_output(items: Any) -> bool:
    """Whether the pipeline iterates the REST framework's own generator, with no source wrapper around it."""
    return isinstance(items, Resource)
