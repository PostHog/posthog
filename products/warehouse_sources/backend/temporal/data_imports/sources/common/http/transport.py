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
from collections.abc import Mapping
from typing import Any

import requests
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InvalidHeader
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import record_request


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
    """

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
    """

    def __init__(self, *args: Any, redact_values: tuple[str, ...] = (), capture: bool = True, **kwargs: Any) -> None:
        self._redact_values = redact_values
        self._capture = capture
        super().__init__(*args, **kwargs)

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        started = time.monotonic()
        response: Response | None = None
        exception: BaseException | None = None
        try:
            response = super().send(
                request,
                stream=stream,
                timeout=timeout,
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
