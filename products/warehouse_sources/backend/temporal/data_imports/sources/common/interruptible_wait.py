"""A wait that ends when the worker starts to shut down, or when the pipeline leaves the source.

A source that sleeps through a backoff or a rate limit hold yields nothing in that time, so the
pipeline cannot hand the run to another worker until the sleep ends. `interruptible_wait` polls the
shutdown signal that the pipeline installs with the safe point. Outside such a run it is a plain
sleep, because a run that cannot resume loses its progress when it stops early.

A wait also ends, with `SourceAbandonedError`, when the pipeline no longer reads the source. The
thread of the source then stops its retries and its requests instead of waiting on.
"""

import time
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.abandonable_iterate import (
    SourceAbandonedError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.progress import RETRY_WAIT, note_progress
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import shutdown_signal

# The longest time a wait continues after the worker starts to shut down.
WAIT_SLICE_SECONDS = 1.0


class SourceWaitSignals:
    """What the pipeline tells the waits of one source."""

    def __init__(self) -> None:
        self._abandoned = threading.Event()

    def notify_abandoned(self) -> None:
        self._abandoned.set()

    @property
    def is_abandoned(self) -> bool:
        return self._abandoned.is_set()

    def wait(self, seconds: float) -> bool:
        """Wait up to `seconds`. Return True when the source was abandoned in that time."""
        return self._abandoned.wait(max(seconds, 0.0))


_active_signals: ContextVar[SourceWaitSignals | None] = ContextVar("warehouse_source_wait_signals", default=None)


@contextmanager
def activate_wait_signals(signals: SourceWaitSignals) -> Iterator[None]:
    """Install `signals` for code that runs in this context, including source threads started in it."""
    token = _active_signals.set(signals)
    try:
        yield
    finally:
        _active_signals.reset(token)


def interruptible_wait(seconds: float, *, safe_point: Callable[[], None] | None = None) -> bool:
    """Wait `seconds`, or less when the worker starts to shut down. Return True when the wait ended early.

    Pass `safe_point` only from a position where the run can stop and resume without losing rows.
    It runs when the worker is shutting down, and the pipeline's hook then raises
    `WorkerShuttingDownError`. A caller that cannot know the position of the source (the HTTP
    adapter, a request pacer on a pool thread) passes none and gets the early return only.

    Raises `SourceAbandonedError` when the pipeline no longer reads the source.
    """
    # A wait is a decision of the source, so the thread is not blocked in a call.
    note_progress(RETRY_WAIT)
    is_shutting_down = shutdown_signal()
    signals = _active_signals.get()
    if is_shutting_down is None and signals is None:
        time.sleep(seconds)
        return False

    remaining = seconds
    while True:
        if signals is not None and signals.is_abandoned:
            raise SourceAbandonedError("The pipeline no longer reads this source, so its wait ends")
        if is_shutting_down is not None and is_shutting_down():
            if safe_point is not None:
                safe_point()
            return True
        if remaining <= 0:
            return False
        step = min(remaining, WAIT_SLICE_SECONDS)
        if signals is not None:
            signals.wait(step)
        else:
            time.sleep(step)
        remaining -= step
