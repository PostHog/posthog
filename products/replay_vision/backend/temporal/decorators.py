"""Decorators that instrument Replay Vision activity bodies."""

import time
import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from asgiref.sync import sync_to_async

from posthog.temporal.common.utils import close_stale_db_connections

from products.replay_vision.backend.temporal.metrics import record_activity_duration, record_side_effect_failure

F = TypeVar("F", bound=Callable[..., Any])


def track_activity(
    name: str | None = None, side_effect: str | None = None, close_stale_db: bool = False
) -> Callable[[F], F]:
    """Wrap an activity body to record `replay_vision_activity_duration_seconds`; apply below `@activity.defn`.

    Pass `side_effect` on fail-soft post-success activities so their failed attempts also
    count into `replay_vision_side_effect_failures_total`. The workflow swallows their
    errors, so nothing downstream would surface the degradation.

    Pass `close_stale_db=True` on an async activity that reads Postgres through Django's native
    async ORM (afirst/acreate). Those run their query on asgiref's shared thread-sensitive
    executor, whose long-lived thread keeps expired connections between runs. Leave it False for
    async activities that touch no database, or that route their database work through a pool
    (thread_sensitive=False); the cleanup would only queue them onto the shared thread for no gain.
    """

    def decorator(fn: F) -> F:
        label = name or fn.__name__

        def _record(status: str, started: float) -> None:
            record_activity_duration(label, status, time.monotonic() - started)
            if status == "failed" and side_effect is not None:
                record_side_effect_failure(side_effect)

        if inspect.iscoroutinefunction(fn):
            # Close on the shared thread-sensitive executor, the same thread the native async ORM
            # runs its query on, so the connection the query reuses is the one closed. A pool thread
            # would close a different, thread-local connection and leave the stale one in place.
            close_stale_db_connections_async = (
                sync_to_async(close_stale_db_connections, thread_sensitive=True) if close_stale_db else None
            )

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if close_stale_db_connections_async is not None:
                    await close_stale_db_connections_async()
                started = time.monotonic()
                try:
                    result = await fn(*args, **kwargs)
                except Exception:
                    _record("failed", started)
                    raise
                _record("succeeded", started)
                return result

            return cast(F, async_wrapper)

        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Long-lived worker threads accumulate expired Postgres connections between activity runs.
            close_stale_db_connections()
            started = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except Exception:
                _record("failed", started)
                raise
            _record("succeeded", started)
            return result

        return cast(F, sync_wrapper)

    return decorator
