import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

# vLLM has no abort hook for IO processors, so entries of requests rejected or dropped after pre_process expire instead.
PENDING_MAX_AGE_SECONDS = 300


@dataclass
class _Entry[T]:
    request_id: str | None
    value: T
    created: float
    taken: bool = False


class PendingRequests[T]:
    """What pre_process knew about a request, kept until post_process; vLLM calls both with the same request id and
    may run them on executor threads, so every access is serialised."""

    def __init__(self, max_age_seconds: float = PENDING_MAX_AGE_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._by_id: dict[str | None, deque[_Entry[T]]] = {}
        self._by_age: deque[_Entry[T]] = deque()
        self._lock = threading.Lock()
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    def put(self, request_id: str | None, value: T) -> None:
        with self._lock:
            now = self._clock()
            self._expire_older_than(now - self._max_age_seconds)
            entry = _Entry(request_id, value, now)
            self._by_id.setdefault(request_id, deque()).append(entry)
            self._by_age.append(entry)

    def take(self, request_id: str | None) -> T:
        with self._lock:
            self._expire_older_than(self._clock() - self._max_age_seconds)
            entries = self._by_id.get(request_id)
            if not entries:
                raise ValueError(f"request {request_id} waited longer than {self._max_age_seconds}s and expired")
            entry = entries.popleft()
            if not entries:
                del self._by_id[request_id]
            entry.taken = True
            return entry.value

    def _expire_older_than(self, cutoff: float) -> None:
        while self._by_age and (self._by_age[0].taken or self._by_age[0].created < cutoff):
            entry = self._by_age.popleft()
            if entry.taken:
                continue
            entries = self._by_id[entry.request_id]
            entries.popleft()
            if not entries:
                del self._by_id[entry.request_id]
