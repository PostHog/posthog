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

import time
from collections.abc import Mapping
from typing import Any

import requests
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import record_request

DEFAULT_RETRY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
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
