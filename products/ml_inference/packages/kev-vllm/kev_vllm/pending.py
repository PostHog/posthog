import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable

# vLLM has no abort hook for IO processors, so entries of requests rejected or dropped after pre_process expire instead.
PENDING_MAX_AGE_SECONDS = 300


class PendingRequests[T]:
    """What pre_process knew about a request, kept until post_process; vLLM calls both with the same request id and
    may run them on executor threads, so every access is serialised."""

    def __init__(self, max_age_seconds: float = PENDING_MAX_AGE_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: OrderedDict[str | None, deque[tuple[T, float]]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    def put(self, request_id: str | None, value: T) -> None:
        with self._lock:
            now = self._clock()
            self._expire_older_than(now - self._max_age_seconds)
            self._entries.setdefault(request_id, deque()).append((value, now))

    def take(self, request_id: str | None) -> T:
        with self._lock:
            entries = self._entries.get(request_id)
            if not entries:
                raise ValueError(f"request {request_id} waited longer than {self._max_age_seconds}s and expired")
            value, _ = entries.popleft()
            if not entries:
                del self._entries[request_id]
            return value

    def _expire_older_than(self, cutoff: float) -> None:
        # The newest entry under an id decides, so a reused id never loses a fresh entry.
        while self._entries:
            request_id, entries = next(iter(self._entries.items()))
            if entries[-1][1] >= cutoff:
                return
            del self._entries[request_id]
