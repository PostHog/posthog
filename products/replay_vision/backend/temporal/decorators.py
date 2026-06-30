"""Decorators that instrument Replay Vision activity bodies."""

import time
import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from products.replay_vision.backend.temporal.metrics import REPLAY_VISION_ACTIVITY_DURATION

F = TypeVar("F", bound=Callable[..., Any])


def track_activity(name: str | None = None) -> Callable[[F], F]:
    """Wrap an activity body to record `replay_vision_activity_duration_seconds`; apply below `@activity.defn`."""

    def decorator(fn: F) -> F:
        label = name or fn.__name__

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                started = time.monotonic()
                try:
                    result = await fn(*args, **kwargs)
                except Exception:
                    REPLAY_VISION_ACTIVITY_DURATION.labels(activity=label, status="failed").observe(
                        time.monotonic() - started
                    )
                    raise
                REPLAY_VISION_ACTIVITY_DURATION.labels(activity=label, status="succeeded").observe(
                    time.monotonic() - started
                )
                return result

            return cast(F, async_wrapper)

        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except Exception:
                REPLAY_VISION_ACTIVITY_DURATION.labels(activity=label, status="failed").observe(
                    time.monotonic() - started
                )
                raise
            REPLAY_VISION_ACTIVITY_DURATION.labels(activity=label, status="succeeded").observe(
                time.monotonic() - started
            )
            return result

        return cast(F, sync_wrapper)

    return decorator
