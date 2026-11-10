"""A wait that ends when the worker starts to shut down.

A source that sleeps through a backoff or a rate limit hold yields nothing in that time, so the
pipeline cannot hand the run to another worker until the sleep ends. `interruptible_wait` polls the
shutdown signal that the pipeline installs with the safe point. Outside such a run it is a plain
sleep, because a run that cannot resume loses its progress when it stops early.
"""

import time
from collections.abc import Callable

from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import shutdown_signal

# The longest time a wait continues after the worker starts to shut down.
WAIT_SLICE_SECONDS = 1.0


def interruptible_wait(seconds: float, *, safe_point: Callable[[], None] | None = None) -> bool:
    """Wait `seconds`, or less when the worker starts to shut down. Return True when the wait ended early.

    Pass `safe_point` only from a position where the run can stop and resume without losing rows.
    It runs when the worker is shutting down, and the pipeline's hook then raises
    `WorkerShuttingDownError`. A caller that cannot know the position of the source (the HTTP
    adapter, a request pacer on a pool thread) passes none and gets the early return only.
    """
    is_shutting_down = shutdown_signal()
    if is_shutting_down is None:
        time.sleep(seconds)
        return False

    remaining = seconds
    while True:
        if is_shutting_down():
            if safe_point is not None:
                safe_point()
            return True
        if remaining <= 0:
            return False
        step = min(remaining, WAIT_SLICE_SECONDS)
        time.sleep(step)
        remaining -= step
