"""One deadline for all tries of a request that a source retries itself.

The tracked adapter gives each `send()` one deadline. A source that wraps its requests in its own
retry loop calls `send()` again for each try, so each try starts a new deadline. The adapter also
retries inside each try. A stalled vendor then holds the worker for the source tries, times the
adapter tries, times the read timeout.

`retry_with_deadline` replaces `tenacity.retry`. It starts one deadline when the decorated call
starts. All tries of the call, and the adapter retries inside them, end by that deadline. The loop
stops before a wait that the deadline cannot pay for.

The adapter keeps its own retries inside the deadline. The two layers share the deadline, so they
cannot hold the worker past it. A source that relies on the adapter to retry a 429 or a 5xx keeps
those retries.
"""

from __future__ import annotations

import time
import inspect
import functools
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

import tenacity
from tenacity import RetryCallState
from tenacity.stop import stop_base

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    current_request_deadline,
    request_deadline,
)

P = ParamSpec("P")
R = TypeVar("R")

# Returns the delay that the server asked for (for example a `Retry-After` value) before the source caps it.
RequestedWait = Callable[[RetryCallState], float | None]


class stop_at_request_deadline(stop_base):
    """A tenacity stop condition: stop before a wait that ends at or after the request deadline.

    The deadline is the one of the enclosing `request_deadline` block. No time is left for a try
    after such a wait. Outside a `request_deadline` block, the condition never stops the loop.

    Give `requested_wait` when the source caps a server-provided delay. A capped wait ends before
    the server is ready, so the next try fails again. The condition then uses the delay that the
    server asked for.
    """

    def __init__(self, requested_wait: RequestedWait | None = None) -> None:
        self._requested_wait = requested_wait

    def __call__(self, retry_state: RetryCallState) -> bool:
        deadline = current_request_deadline()
        if deadline is None:
            return False
        wait = retry_state.upcoming_sleep
        if self._requested_wait is not None:
            wait = max(wait, self._requested_wait(retry_state) or 0.0)
        # tenacity calls `wait` before `stop`, so `upcoming_sleep` holds the wait that follows this try.
        return time.monotonic() + wait >= deadline


def request_deadline_allows_wait(seconds: float) -> bool:
    """Whether a wait of `seconds` ends before the deadline of the enclosing `request_deadline` block.

    For a hand-written retry loop. With no enclosing block, every wait is allowed.
    """
    deadline = current_request_deadline()
    return deadline is None or time.monotonic() + seconds < deadline


def retry_with_deadline(
    *,
    stop: Callable[[RetryCallState], bool] | None = None,
    requested_wait: RequestedWait | None = None,
    **retry_kwargs: Any,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """`tenacity.retry`, with one deadline for all tries of each call.

    The deadline is `retry_budget_seconds()` from the start of the call. The loop stops on `stop`,
    or before a wait that passes the deadline.
    The other keyword arguments go to `tenacity.retry` unchanged.

    Put it on a function that sends one logical request. All requests in the call share the
    deadline, so a function that pages through a whole collection would fail after the deadline.
    """
    deadline_stop = stop_at_request_deadline(requested_wait)
    with_retries = tenacity.retry(stop=_combined_stop(stop, deadline_stop), **retry_kwargs)

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        if inspect.isgeneratorfunction(fn) or inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
            # tenacity retries only the creation of a generator, and the deadline block would end before
            # the generator or the coroutine runs. Such a source keeps `tenacity.retry`.
            raise TypeError(f"retry_with_deadline supports plain functions only, not {fn.__qualname__}")
        return _with_deadline(cast(Callable[P, R], with_retries(fn)), fn, deadline_stop)

    return decorate


def _combined_stop(stop: Callable[[RetryCallState], bool] | None, deadline_stop: stop_base) -> stop_base:
    return deadline_stop if stop is None else tenacity.stop_any(cast(stop_base, stop), deadline_stop)


def _with_deadline(retried: Callable[P, R], fn: Callable[P, R], deadline_stop: stop_base) -> Callable[P, R]:
    @functools.wraps(retried)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        with request_deadline():
            return retried(*args, **kwargs)

    # `functools.wraps` copies the `retry` controller of the tenacity wrapper, which the contract
    # harness and source tests patch. Tests also call `__wrapped__` to run one try with no retries,
    # so it stays the undecorated function, as with `tenacity.retry`.
    wrapper = cast(Any, call)
    wrapper.__wrapped__ = fn
    wrapper.retry_with = functools.partial(_retry_with, retried, fn, deadline_stop)
    return call


def _retry_with(
    retried: Callable[P, R], fn: Callable[P, R], deadline_stop: stop_base, *args: Any, **kwargs: Any
) -> Callable[P, R]:
    # A `stop` given here replaces the whole stop condition in tenacity, so it is combined with the deadline again.
    if "stop" in kwargs:
        kwargs["stop"] = _combined_stop(kwargs["stop"], deadline_stop)
    return _with_deadline(cast(Any, retried).retry_with(*args, **kwargs), fn, deadline_stop)
