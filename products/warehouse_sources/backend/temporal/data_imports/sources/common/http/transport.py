"""Tracked `requests.Session` factory.

`make_tracked_session(...)` returns a `requests.Session` whose adapters
intercept every dispatched request to feed the observer. Vendor SDKs that
accept a `requests.Session` (Stripe via `stripe.RequestsClient`, gspread,
hubspot-api-client, etc.) can be handed the result of this factory.

The intercept point is the adapter's `send()` rather than a `Session`
subclass, because some SDKs construct their own `Session` and we still
want the metering — they only need to mount the tracked adapter:

    session.mount("https://", make_tracked_adapter(...))
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast
from urllib.parse import urlparse

from django.conf import settings

import requests
import structlog
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InvalidHeader, MaxRetryError, ResponseError
from urllib3.util.retry import Retry
from urllib3.util.timeout import Timeout

from posthog.cloud_utils import is_cloud
from posthog.security.oob_domains import matched_oob_domain

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import record_request
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.retry_limits import retry_budget_seconds

logger = structlog.get_logger(__name__)

RequestTimeout = float | tuple[float, float] | tuple[float, None]

# Pass this as `timeout` to send a request with no deadline. `None` does not do that: `requests`
# passes `None` for every call that names no timeout, so `None` means "use the default".
# The cast is for the `requests` stubs, which reject a `None` connect value that `requests` accepts.
NO_REQUEST_TIMEOUT: RequestTimeout = cast(RequestTimeout, (None, None))


def default_request_timeout() -> RequestTimeout:
    """The (connect, read) timeout for a request that names none."""
    return (
        settings.DATA_WAREHOUSE_SOURCE_CONNECT_TIMEOUT_SECONDS,
        settings.DATA_WAREHOUSE_SOURCE_READ_TIMEOUT_SECONDS,
    )


def resolve_request_timeout(timeout: RequestTimeout | None) -> RequestTimeout:
    return default_request_timeout() if timeout is None else timeout


def _monotonic() -> float:
    # Read at each call, so a fake clock that replaces `time.monotonic` reaches the deadlines too.
    return time.monotonic()


# A try never gets a timeout shorter than this. urllib3 rejects a timeout of 0.
_SHORTEST_TRY_SECONDS = 0.001

_request_deadline: ContextVar[float | None] = ContextVar("warehouse_source_request_deadline", default=None)


def current_request_deadline() -> float | None:
    """The deadline of the enclosing `request_deadline` block, a `time.monotonic()` value, if any."""
    return _request_deadline.get()


@contextmanager
def request_deadline(deadline: float | None = None) -> Iterator[None]:
    """Make requests in the block end by `deadline`, a `time.monotonic()` value.

    For a caller that retries a request itself, so that all of its tries share one deadline. Each
    try gets only the time that is left, and the adapter starts no retry that the deadline cuts off.
    An earlier deadline that is already in effect wins. With no `deadline`, the block ends
    `retry_budget_seconds()` from now.
    """
    if deadline is None:
        deadline = _monotonic() + retry_budget_seconds()
    current = _request_deadline.get()
    token = _request_deadline.set(deadline if current is None else min(current, deadline))
    try:
        yield
    finally:
        _request_deadline.reset(token)


def _cut(seconds: Any, left: float) -> Any:
    # None means no deadline, and urllib3 uses a sentinel object for its own default. Both stay as they are.
    if isinstance(seconds, int | float):
        return min(float(seconds), left)
    return seconds


class _DeadlineTimeout(Timeout):
    """A urllib3 `Timeout` that cuts the timeouts of each try to the time left before a deadline.

    urllib3 clones the timeout at the start of each try, also for the adapter's own retries.
    """

    def __init__(self, connect: Any, read: Any, total: Any, *, deadline: float) -> None:
        super().__init__(connect=connect, read=read, total=total)
        self._try_connect = connect
        self._try_read = read
        self._deadline = deadline

    def clone(self) -> Timeout:
        left = max(self._deadline - _monotonic(), _SHORTEST_TRY_SECONDS)
        total = _cut(self.total, left)
        # Connect and read time add up, so a total is what keeps a slow connect from adding to the read.
        # A timeout that sets no connect or no read stays open, because that is the source's opt-out.
        if total is None and self._try_connect is not None and self._try_read is not None:
            total = left
        return Timeout(connect=_cut(self._try_connect, left), read=_cut(self._try_read, left), total=total)


def _deadline_timeout(timeout: RequestTimeout | Timeout, deadline: float) -> _DeadlineTimeout:
    # Some sources pass a urllib3 `Timeout`, which `requests` accepts too.
    if isinstance(timeout, Timeout):
        raw = cast(Any, timeout)  # the stubs hide the configured values, and `connect_timeout` needs a started clock
        return _DeadlineTimeout(raw._connect, raw._read, timeout.total, deadline=deadline)
    connect, read = timeout if isinstance(timeout, tuple) else (timeout, timeout)
    return _DeadlineTimeout(connect, read, None, deadline=deadline)


# The same policy as the `requests` default: no retry, and a read error keeps its own type.
NO_RETRY = Retry(0, read=False)

_adapter_retries_suspended: ContextVar[bool] = ContextVar("warehouse_source_adapter_retries_suspended", default=False)


@contextmanager
def suspend_adapter_retries() -> Iterator[None]:
    """Send requests in the block with no adapter-level retry.

    For a caller that owns the retries of its requests. Two retry layers multiply their tries and
    their waits, and only the outer one can reach a safe point before a wait.
    """
    token = _adapter_retries_suspended.set(True)
    try:
        yield
    finally:
        _adapter_retries_suspended.reset(token)


class BoundedRetry(Retry):
    """`Retry` that hardens `Retry-After` handling against hostile or sloppy servers.

    Two failure modes are covered:

    - A server can send a `Retry-After` far larger than any sane wait — an absurd
      integer or a date decades out. urllib3 passes it straight to `time.sleep`,
      which raises `OverflowError` once it exceeds what a C `PyTime_t` can hold,
      killing the sync. `get_retry_after` bounds it to the backoff ceiling, keeping
      a hostile value from overflowing (and from parking a worker for hours).
    - RFC 9110 requires `Retry-After` to be an integer delay-seconds or an
      HTTP-date, and urllib3's default parsing raises `InvalidHeader` on anything
      else. Some upstream APIs send fractional seconds (e.g. "0.129") instead, which
      otherwise turns a should-be-transient rate limit into a hard failure.
      `parse_retry_after` tolerates fractional values and falls back to no delay.

    Two more limits keep one request from holding a worker:

    - All tries of one request end by one deadline. In `TrackedHTTPAdapter` it is the request
      deadline (see `request_deadline`). Outside it, it is `retry_budget_seconds()` after the first
      failure. No wait starts that would end at or after the deadline: the last response or error
      goes to the caller. A `Retry-After` counts with the delay that the server asked for, before
      the cap, so a server that asks for a day gets its 429 back at once and no capped wait.
    - A wait ends early when the worker starts to shut down, so the caller can hand the run off.
    """

    def __init__(self, *args: Any, retry_deadline: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._retry_deadline = retry_deadline

    def new(self, **kw: Any) -> BoundedRetry:
        # urllib3 builds a new object for each try, so the deadline must travel with it.
        kw.setdefault("retry_deadline", self._retry_deadline)
        return cast(BoundedRetry, super().new(**kw))

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: Any = None,
        error: Exception | None = None,
        _pool: Any = None,
        _stacktrace: Any = None,
    ) -> BoundedRetry:
        retry = cast(
            BoundedRetry,
            super().increment(
                method=method, url=url, response=response, error=error, _pool=_pool, _stacktrace=_stacktrace
            ),
        )
        now = _monotonic()
        deadline = _request_deadline.get()
        if deadline is None:
            deadline = now + retry_budget_seconds() if self._retry_deadline is None else self._retry_deadline
        if now + retry._requested_wait(response) >= deadline:
            raise MaxRetryError(_pool, url or "", error or ResponseError("retry budget spent"))
        retry._retry_deadline = deadline
        return retry

    def _requested_wait(self, response: Any) -> float:
        # The same choice as `Retry.sleep`, which urllib3 calls on the object that `increment` returns,
        # but with the delay the server asked for and not the capped one. A capped wait ends before the
        # server is ready, so a retry after it fails again and only holds the worker.
        if self.respect_retry_after_header and response is not None:
            retry_after = super().get_retry_after(response)
            if retry_after:
                return retry_after
        return self.get_backoff_time()

    def sleep_for_retry(self, response: Any = None) -> bool:
        retry_after = self.get_retry_after(response)
        if retry_after:
            interruptible_wait(retry_after)
            return True
        return False

    def _sleep_backoff(self) -> None:
        backoff = self.get_backoff_time()
        if backoff > 0:
            interruptible_wait(backoff)

    def parse_retry_after(self, retry_after: str) -> float:
        try:
            return super().parse_retry_after(retry_after)
        except InvalidHeader:
            try:
                seconds = float(retry_after)
            except ValueError:
                return 0.0
            # `float()` accepts "NaN"/"Infinity"; a non-finite delay would slip past
            # `min()`/`max()` (which don't order NaN) and reach `time.sleep`, raising
            # ValueError. Treat non-finite values as "no delay".
            if not math.isfinite(seconds):
                return 0.0
            return max(seconds, 0.0)

    def get_retry_after(self, response: Any) -> float | None:
        retry_after = super().get_retry_after(response)
        if retry_after is None:
            return None
        return min(retry_after, self.DEFAULT_BACKOFF_MAX)


# Cloudflare returns the 52x family for a slow or unreachable origin: 520 (Unknown Error), 521 (Web
# Server Down), 522 (Connection Timed Out), 523 (Origin Unreachable), 524 (A Timeout Occurred), plus
# 530 (edge-side DNS hiccup). These are transient like the standard 502/503/504, so retry them the
# same way. A source behind Cloudflare (Cal.com, Convex, DoiT) otherwise records a raw 52x as a
# failure. Retries are safe because only GET/HEAD/OPTIONS are retried; a persistent 52x still
# surfaces after the attempt budget because raise_on_status is False.
CLOUDFLARE_TRANSIENT_STATUSES = (520, 521, 522, 523, 524, 530)

DEFAULT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504, *CLOUDFLARE_TRANSIENT_STATUSES),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    raise_on_status=False,
)


def _note_oob_domain(request: PreparedRequest) -> None:
    """Record a request to an out-of-band interaction domain, without refusing it.

    `requests` re-enters the adapter on every redirect hop, so a hop to a listed host is recorded
    as well as the first request.
    """
    if not is_cloud():
        return

    try:
        host = urlparse(request.url or "").hostname
    except Exception as exc:
        # Detection never fails a request: a malformed URL is the connection's problem to report.
        # `requests` rejects a URL it cannot parse before `send()`, so reaching this means the two
        # parsers disagree. The URL stays out of the line because it carries the credential that
        # `record_request` scrubs; it logs the same request a moment later.
        logger.warning("security.oob_domain_url_unparsed", error=type(exc).__name__)
        return

    if host is None:
        return

    try:
        oob_domain = matched_oob_domain(host)
    except Exception:
        logger.exception("security.oob_domain_check_failed", host=host)
        return

    if oob_domain is not None:
        logger.info("security.oob_domain_seen", host=host, domain=oob_domain, guard="warehouse_http")


class TrackedHTTPAdapter(HTTPAdapter):
    """`HTTPAdapter` that records every dispatched request via the observer.

    `send()` is the lowest synchronous hook in the requests stack — it sees
    the fully-prepared request and the raw response, exception or not, with
    no SDK-specific framing on top.

    `redact_values` are credential strings to mask wherever they appear in the
    logged URL or captured sample — value-based masking that complements the
    name-based denylists for auth injected under an unpredictable param/header
    name (e.g. an API key in a query param).

    `capture=False` keeps requests metered and logged but excludes them from HTTP
    sample capture — for auth exchanges whose bodies carry secrets the name-based
    scrubbers can't recognise (e.g. a minted session token in a generic `id` field).

    A request that reaches `send()` with `timeout=None` gets `default_request_timeout()`, so a
    stalled host cannot hold a worker without limit. Pass `NO_REQUEST_TIMEOUT` to opt out.

    All tries of one `send()` end by one deadline: the caller's `request_deadline`, or
    `retry_budget_seconds()` after the call starts.
    """

    def __init__(self, *args: Any, redact_values: tuple[str, ...] = (), capture: bool = True, **kwargs: Any) -> None:
        self._redact_values = redact_values
        self._capture = capture
        super().__init__(*args, **kwargs)

    @property
    def max_retries(self) -> Retry:
        return NO_RETRY if _adapter_retries_suspended.get() else self._max_retries

    @max_retries.setter
    def max_retries(self, value: Retry) -> None:
        self._max_retries = value

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: RequestTimeout | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        _note_oob_domain(request)
        started = time.monotonic()
        deadline = _request_deadline.get()
        if deadline is None:
            deadline = _monotonic() + retry_budget_seconds()
        response: Response | None = None
        exception: BaseException | None = None
        try:
            with request_deadline(deadline):
                response = super().send(
                    request,
                    stream=stream,
                    # `requests` accepts a urllib3 `Timeout` here, which its stubs do not list.
                    timeout=cast(Any, _deadline_timeout(resolve_request_timeout(timeout), deadline)),
                    verify=verify,
                    cert=cert,
                    proxies=proxies,
                )
            return response
        except BaseException as exc:
            exception = exc
            raise
        finally:
            try:
                record_request(
                    request,
                    response,
                    started_at_monotonic=started,
                    exception=exception,
                    redact_values=self._redact_values,
                    capture=self._capture,
                    streamed=stream,
                )
            except Exception:
                # Belt-and-braces: record_request should never raise, but if
                # something does we never want to mask the real outcome.
                pass


def make_tracked_adapter(
    retry: Retry | None = None, redact_values: tuple[str, ...] = (), capture: bool = True, **kwargs: Any
) -> TrackedHTTPAdapter:
    """Construct a `TrackedHTTPAdapter`.

    `retry=None` (the default) uses the built-in `DEFAULT_RETRY` policy. To
    truly opt out of retries, pass `retry=Retry(total=0)`. To override with
    different retry settings, pass a custom `Retry` instance. Any extra
    kwargs are forwarded to `HTTPAdapter.__init__`. `redact_values` are
    credential strings to mask in logged URLs and captured samples. `capture=False`
    excludes requests from HTTP sample capture (still metered and logged).
    """
    if retry is None:
        retry = DEFAULT_RETRY
    return TrackedHTTPAdapter(max_retries=retry, redact_values=redact_values, capture=capture, **kwargs)


class _NoRedirectSession(requests.Session):
    """`requests.Session` that never follows redirects.

    Defense-in-depth for SSRF-sensitive sources. The load-bearing SSRF control
    is the Smokescreen egress proxy that data-warehouse outbound traffic flows
    through — it re-resolves and blocks internal/metadata hosts on every hop, so
    DNS-rebinding and redirect chains are handled there. Pinning `allow_redirects`
    off is a cheap extra layer that keeps a connector's traffic pointed at the
    host it validated. `requests` reads `allow_redirects` per call and callers
    like `RESTClient` invoke `send()` without it (so it defaults to `True`), so we
    pin it off at the session level.
    """

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        kwargs["allow_redirects"] = False
        return super().send(request, **kwargs)


def make_tracked_session(
    *,
    retry: Retry | None = None,
    headers: dict[str, str] | None = None,
    redact_values: tuple[str, ...] = (),
    allow_redirects: bool = True,
    capture: bool = True,
) -> requests.Session:
    """Return a fresh `requests.Session` with tracked HTTP/HTTPS adapters.

    See `make_tracked_adapter` for the `retry` parameter semantics — `None`
    uses `DEFAULT_RETRY`; pass `Retry(total=0)` to disable retries.
    `redact_values` are credential strings to mask in logged URLs and captured
    samples — for auth injected under a param/header name the denylist can't
    predict (e.g. an API key in a query param).
    `allow_redirects=False` returns a session that never follows redirects — an
    SSRF boundary for sources that fetch user-supplied hosts (see `_NoRedirectSession`).
    `capture=False` excludes the session's requests from HTTP sample capture (still
    metered and logged) — for auth exchanges whose bodies carry secrets the name-based
    scrubbers can't recognise (e.g. a minted session token in a generic `id` field).
    """
    session: requests.Session = requests.Session() if allow_redirects else _NoRedirectSession()
    adapter = make_tracked_adapter(retry=retry, redact_values=redact_values, capture=capture)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if headers:
        session.headers.update(headers)
    return session
