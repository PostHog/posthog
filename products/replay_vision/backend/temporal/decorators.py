"""Decorators that instrument Replay Vision activity bodies."""

import time
import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

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

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
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
