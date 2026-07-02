"""Decorators that instrument Replay Vision activity bodies."""

import time
import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.temporal.metrics import REPLAY_VISION_ACTIVITY_DURATION

F = TypeVar("F", bound=Callable[..., Any])


def track_activity(name: str | None = None) -> Callable[[F], F]:
    """Wrap an activity body to record `replay_vision_activity_duration_seconds` and evict stale DB connections.

    Apply below `@activity.defn`. The `close_db_connections` wrapping matters because these activities run in a
    long-lived Temporal worker that never goes through Django's request cycle, so `close_old_connections()` never
    fires. A pooled connection killed by a pgbouncer recycle, DB failover, or deploy would otherwise stay in the
    pool until the next query hits it and blows up with `ProtocolViolation: unknown pkt`. Evicting around every
    activity body hands each one a fresh connection instead of a poisoned pooled one.
    """

    def decorator(fn: F) -> F:
        label = name or fn.__name__
        # Evict stale connections around the body so a poisoned pooled connection can't leak into it.
        fn = cast(F, close_db_connections(fn))

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
