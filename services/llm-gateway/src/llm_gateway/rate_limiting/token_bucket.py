import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class Bucket:
    tokens: float
    last_update: float


@dataclass
class TokenBucketLimiter:
    rate: float
    capacity: float
    _buckets: dict[str, Bucket] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def consume(self, key: str, tokens: float = 1.0) -> bool:
        now = time.monotonic()

        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = Bucket(tokens=self.capacity, last_update=now)

            bucket = self._buckets[key]
            elapsed = now - bucket.last_update
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.rate)
            bucket.last_update = now

            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()
