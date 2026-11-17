import time
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from prometheus_client import Histogram

F = TypeVar("F", bound=Callable)

SKILLS_REQUEST_LATENCY = Histogram(
    "skills_request_duration_seconds",
    "Skills API request latency in seconds",
    labelnames=["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)


def skills_track_latency(endpoint: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                SKILLS_REQUEST_LATENCY.labels(endpoint=endpoint).observe(time.perf_counter() - start)

        return wrapper  # type: ignore[return-value]  # ty: ignore[invalid-return-type]

    return decorator
