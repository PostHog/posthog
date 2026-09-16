import time
import threading
from collections.abc import Callable
from typing import Optional

# How long a 429 keeps the pool at a reduced rate when the vendor sends no Retry-After.
RATE_LIMIT_HOLD_SECONDS = 30.0


class RequestPacer:
    """Spaces request starts across threads and slows the whole pool after a rate limit.

    Every worker calls wait_turn() before a request, so the pool never starts more than
    `per_second` requests in any second. A 429 halves the rate for the hold window and, when
    the vendor sends Retry-After, holds every worker until it passes, including workers already
    waiting for a slot. Each quiet window after that doubles the rate back until the base rate
    is restored.

    The budget being protected belongs to the customer's own account on the vendor, so this is a
    caller-side courtesy rather than a shared PostHog budget. An API whose credential PostHog owns
    belongs in `posthog/egress/` instead.
    """

    def __init__(
        self,
        per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_interval = 1.0 / per_second
        self._interval = self._base_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_start = 0.0
        self._hold_until = 0.0
        self._recover_at: Optional[float] = None

    def wait_turn(self) -> None:
        start = self._reserve_slot()
        while True:
            delay = start - self._clock()
            if delay > 0:
                self._sleep(delay)
            with self._lock:
                if self._hold_until <= start:
                    return
            # A throttle arrived during the sleep and its hold covers this slot: take a later one.
            start = self._reserve_slot()

    def _reserve_slot(self) -> float:
        with self._lock:
            now = self._clock()
            if self._recover_at is not None and now >= self._recover_at:
                self._interval = max(self._interval / 2, self._base_interval)
                self._recover_at = None if self._interval == self._base_interval else now + RATE_LIMIT_HOLD_SECONDS
            start = max(now, self._next_start)
            self._next_start = start + self._interval
            return start

    def throttled(self, retry_after: Optional[float]) -> None:
        with self._lock:
            now = self._clock()
            if now < self._hold_until:
                # Requests already in flight when the first 429 landed report the same throttle.
                return
            hold = retry_after if retry_after is not None and retry_after > 0 else RATE_LIMIT_HOLD_SECONDS
            self._interval = min(self._interval * 2, self._base_interval * 16)
            if retry_after is not None and retry_after > 0:
                self._hold_until = now + retry_after
                self._next_start = max(self._next_start, self._hold_until)
            self._recover_at = now + hold
