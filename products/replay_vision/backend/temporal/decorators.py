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


def track_activity(name: str | None = None, side_effect: str | None = None) -> Callable[[F], F]:
    """Wrap an activity body to record `replay_vision_activity_duration_seconds`; apply below `@activity.defn`.

    Pass `side_effect` on fail-soft post-success activities so their failed attempts also
    count into `replay_vision_side_effect_failures_total`. The workflow swallows their
    errors, so nothing downstream would surface the degradation.
    """

    def decorator(fn: F) -> F:
        label = name or fn.__name__

        def _record(status: str, started: float) -> None:
            record_activity_duration(label, status, time.monotonic() - started)
            if status == "failed" and side_effect is not None:
                record_side_effect_failure(side_effect)

        if inspect.iscoroutinefunction(fn):
            # Django's native async ORM (afirst/acreate) runs its query through
            # sync_to_async(thread_sensitive=True), so the connection to close lives on asgiref's
            # shared thread-sensitive executor. Match that thread here. database_sync_to_async_pool
            # would run on a different pool thread and close the wrong connection, because Django
            # connections are thread-local, leaving the stale one the ORM reuses in place.
            close_stale_db_connections_async = sync_to_async(close_stale_db_connections, thread_sensitive=True)

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
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
