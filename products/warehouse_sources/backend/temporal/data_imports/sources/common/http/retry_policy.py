"""The retry policy for a source that sends its own requests.

`RESTClient` retries a 408, a 429 and a 5xx itself, waits as long as the server asks, and turns off
the adapter retries so that only one retry loop runs. A vendor client that calls a tracked session
directly gets the same policy from this module:

    @vendor_retry()
    def _fetch_page(session, url, params):
        response = session.get(url, params=params)
        raise_for_retryable_status(response, vendor="Acme")
        raise_for_status_redacted(response)
        return response.json()

The decorated function sends one logical request. All its tries share one deadline (see
`retry_with_deadline`), so a function that pages through a whole collection must not carry it.
"""

from __future__ import annotations

import inspect
import functools
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ParamSpec, TypeVar

import requests
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.retry_deadline import (
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    suspend_adapter_retries,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import safe_url
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.retry_limits import max_retry_after_seconds

P = ParamSpec("P")
R = TypeVar("R")

# Transport failures that a new try can clear. `requests.Timeout` covers both the connect and the read timeout.
NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


class RetryableHTTPError(NonReportableError):
    """A response that a new try can clear: a 408, a 429 or a 5xx.

    It is a `NonReportableError` because the vendor causes it. When the tries are spent, the error goes
    to the activity, and the activity retry comes back later.
    """

    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def is_retryable_status(status: int) -> bool:
    # 408 is in the set because the server, not the transport, tells the client to come back later.
    return status in (408, 429) or status >= 500


def raise_for_retryable_status(response: requests.Response, *, vendor: str, url: str | None = None) -> None:
    """Raise `RetryableHTTPError` for a 408, a 429 or a 5xx. Do nothing for any other status.

    The message holds the scheme, the host and the path of `url` (default: `response.url`), but never
    the query string, which can hold a credential.
    """
    status = response.status_code
    if not is_retryable_status(status):
        return
    raise RetryableHTTPError(
        f"{vendor} API error (retryable): HTTP {status} for {safe_url(url or response.url or '')}",
        status=status,
        retry_after=parse_retry_after(response),
    )


def raise_for_status_redacted(response: requests.Response, *, url: str | None = None) -> None:
    """`response.raise_for_status()`, but the message never holds the query string.

    The message keeps the stock `"<status> Client Error: <reason> for url: <url>"` shape, so the
    `get_non_retryable_errors` keys of a source, which match it as a substring, keep matching.
    """
    status = response.status_code
    if status < 400:
        return
    kind = "Client" if status < 500 else "Server"
    raise requests.HTTPError(
        f"{status} {kind} Error: {response.reason} for url: {safe_url(url or response.url or '')}",
        response=response,
    )


def vendor_retry(
    *,
    attempts: int = 5,
    retry_on: tuple[type[BaseException], ...] = (),
    backoff_max: float = 30.0,
    max_retry_after: float | None = None,
    suspend_adapter: bool = True,
    safe_point: Callable[[], None] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry `RetryableHTTPError`, `NETWORK_ERRORS` and `retry_on`, up to `attempts` tries in all.

    The wait before a try is the `retry_after` of a `RetryableHTTPError`. Without one, it is an
    exponential backoff with jitter, up to `backoff_max` seconds. When the server asks for a wait longer
    than `max_retry_after` (default: `max_retry_after_seconds()`), the loop stops at once. A server
    that asks for that long does not answer soon, and the activity retry comes back later.

    With `suspend_adapter` (the default), the adapter does not retry the requests of the decorated
    function. This loop then owns all the retries, so the tries and the waits of the two layers do not
    multiply. The decorated function must then raise for each status that it wants to retry, usually
    with `raise_for_retryable_status`.

    Pass `safe_point` (usually `reach_safe_point`) only when the run can stop and resume without
    losing rows before each retry wait, which means that the caller holds no rows that its staged
    cursor covers. It runs before each wait, and again when the worker shuts down during the wait.
    """

    def retry_after_of(state: RetryCallState) -> float | None:
        if state.outcome is None or not state.outcome.failed:
            return None
        exc = state.outcome.exception()
        return exc.retry_after if isinstance(exc, RetryableHTTPError) else None

    def limit() -> float:
        return max_retry_after_seconds() if max_retry_after is None else max_retry_after

    attempts_spent = stop_after_attempt(attempts)
    backoff = wait_exponential_jitter(initial=1, max=backoff_max)

    def stop(state: RetryCallState) -> bool:
        retry_after = retry_after_of(state)
        return attempts_spent(state) or (retry_after is not None and retry_after > limit())

    def wait(state: RetryCallState) -> float:
        retry_after = retry_after_of(state)
        return backoff(state) if retry_after is None else retry_after

    def before_sleep(_state: RetryCallState) -> None:
        if safe_point is not None:
            safe_point()

    def sleep(seconds: float) -> None:
        # Without a safe point, the wait still ends early when the worker shuts down, and the
        # pipeline stops the run at its next item.
        interruptible_wait(seconds, safe_point=safe_point)

    retried = retry_with_deadline(
        retry=retry_if_exception_type((RetryableHTTPError, *NETWORK_ERRORS, *retry_on)),
        stop=stop,
        wait=wait,
        requested_wait=retry_after_of,
        before_sleep=before_sleep,
        sleep=sleep,
        reraise=True,
    )

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        if not suspend_adapter:
            return retried(fn)
        if inspect.isgeneratorfunction(fn) or inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
            # `retry_with_deadline` refuses these too. The check is repeated here because `one_try` hides them.
            raise TypeError(f"vendor_retry supports plain functions only, not {fn.__qualname__}")

        @functools.wraps(fn)
        def one_try(*args: P.args, **kwargs: P.kwargs) -> R:
            with suspend_adapter_retries():
                return fn(*args, **kwargs)

        return retried(one_try)

    return decorate


def parse_retry_after(response: requests.Response) -> float | None:
    """The retry delay in seconds that a rate-limited or failed response asks for, or None.

    Honors the standard ``Retry-After`` header (delta-seconds or HTTP-date) first, then the
    vendor rate-limit reset headers in ``_RATE_LIMIT_RESET_HEADERS``. Without a server-provided
    delay a 429 backs off on the short exponential fallback and the attempt budget is spent long
    before the limit window clears. The value is not capped here: the retry loop fails the request
    when the server asks for more than the client's limit.
    """
    retry_after_header = response.headers.get("Retry-After")
    if retry_after_header:
        try:
            delay = float(retry_after_header)
        except ValueError:
            try:
                dt = parsedate_to_datetime(retry_after_header)
            except (TypeError, ValueError):
                return None
            return max(0.0, (dt - datetime.now(UTC)).total_seconds())
        epoch_wait = _seconds_until_retry_after_epoch(delay)
        if epoch_wait is not None:
            return epoch_wait if epoch_wait > 0 else None
        return max(0.0, delay)

    for header, parse in _RATE_LIMIT_RESET_HEADERS:
        value = response.headers.get(header)
        if not value:
            continue
        wait_seconds = parse(value)
        # A reset already in the past says the window has cleared — nothing to honor, so fall
        # through to the caller's exponential backoff rather than retrying with no delay at all.
        if wait_seconds is None or wait_seconds <= 0:
            return None
        return wait_seconds

    return None


def _seconds_from_epoch_reset(value: str) -> float | None:
    try:
        reset_epoch = int(value)
    except ValueError:
        return None
    return reset_epoch - datetime.now(UTC).timestamp()


# Dub puts the UNIX epoch in milliseconds at which its window resets into ``Retry-After``, not a
# delay. Read as seconds that is a wait of decades, so every 429 failed without a retry. A value
# that, read as epoch seconds or milliseconds, lands this close to now is taken as that instant.
_RETRY_AFTER_EPOCH_WINDOW_SECONDS = 24 * 60 * 60


def _seconds_until_retry_after_epoch(value: float) -> float | None:
    now = datetime.now(UTC).timestamp()
    for reset_epoch in (value, value / 1000):
        if abs(reset_epoch - now) <= _RETRY_AFTER_EPOCH_WINDOW_SECONDS:
            return reset_epoch - now
    return None


def _seconds_from_rfc3339_reset(value: str) -> float | None:
    try:
        reset_at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=UTC)
    return (reset_at - datetime.now(UTC)).total_seconds()


def _seconds_until_anthropic_replenish(value: str) -> float | None:
    # Anthropic documents this instant as the time when the request budget is fully replenished,
    # not the time when the next request is allowed. The bucket refills continuously, so a request
    # usually succeeds long before the instant. An uncapped value of up to an hour made the client
    # fail every 429 at once, so the value is capped at the longest wait the client honors. The
    # client then waits and retries instead.
    seconds = _seconds_from_rfc3339_reset(value)
    if seconds is None:
        return None
    return min(seconds, max_retry_after_seconds())


# Rate-limit reset headers to fall back on when a 429 carries no ``Retry-After``, each paired with
# the parser that turns its value into "seconds from now until the budget replenishes".
_RATE_LIMIT_RESET_HEADERS: tuple[tuple[str, Callable[[str], float | None]], ...] = (
    # Anthropic rate limits per organization and documents this RFC 3339 instant as when the request
    # budget replenishes. Some Admin API report endpoints send it on a 429 without a ``Retry-After``.
    ("anthropic-ratelimit-requests-reset", _seconds_until_anthropic_replenish),
    # Sentry signals its rate-limit window with a UNIX epoch timestamp rather than ``Retry-After``,
    # and Sentry's flat / fan-out endpoints (e.g. ``project_users``) sync through this client too.
    ("X-Sentry-Rate-Limit-Reset", _seconds_from_epoch_reset),
    # X (Twitter) answers 429 with this UNIX epoch reset and no ``Retry-After``. Its windows are 15
    # minutes wide and some endpoints allow only a handful of requests per window, so a backfill
    # that falls back to exponential backoff spends its whole attempt budget inside one window.
    ("x-rate-limit-reset", _seconds_from_epoch_reset),
    # The common ``X-RateLimit-*`` convention, spelled with a UNIX epoch reset and no
    # ``Retry-After`` — SendGrid answers every 429 this way, and its Email Activity endpoint is
    # capped at 6 requests/minute, so without honoring the reset a message-activity backfill
    # spends its whole attempt budget inside a single window. APIs that put delta-seconds in this
    # header parse to an elapsed instant and fall back to exponential backoff.
    ("X-RateLimit-Reset", _seconds_from_epoch_reset),
)
