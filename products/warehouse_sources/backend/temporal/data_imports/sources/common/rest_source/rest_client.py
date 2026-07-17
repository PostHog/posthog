import copy
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urlsplit

from requests import Request, Response, Session
from requests.auth import AuthBase
from requests.exceptions import (
    ChunkedEncodingError,
    HTTPError,
    JSONDecodeError as RequestsJSONDecodeError,
)
from tenacity import RetryCallState, retry, retry_if_exception_type

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

from .auth import auth_secret_values
from .exceptions import IgnoreResponseException
from .jsonpath_utils import TJsonPath, find_values
from .paginators import BasePaginator
from .utils import resolve_request_url

logger = logging.getLogger(__name__)


class RESTClientRetryableError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# Upper bound on how long we'll honor a server-provided retry delay, so a
# misreported header can't stall a worker for an unbounded amount of time.
MAX_RETRY_AFTER_SECONDS = 300.0

# Attempts for the default sync path. The inline preview overrides this to 1 so a
# rate-limited endpoint surfaces an error instead of sleeping on `Retry-After`.
DEFAULT_RETRY_ATTEMPTS = 5


def _parse_retry_after(response: Response) -> Optional[float]:
    """Best-effort retry delay (seconds) from a rate-limited / erroring response.

    Honors the standard ``Retry-After`` header (delta-seconds or HTTP-date)
    first. When it's absent, falls back to Sentry's ``X-Sentry-Rate-Limit-Reset``
    (a UNIX epoch timestamp): Sentry's API signals its rate-limit window with
    that header rather than ``Retry-After``, and Sentry's flat / fan-out
    endpoints (e.g. ``project_users``) sync through this generic client, so
    without it a 429 backs off on the short exponential fallback and exhausts
    retries while still rate-limited. Capped at ``MAX_RETRY_AFTER_SECONDS``.
    """
    retry_after_header = response.headers.get("Retry-After")
    if retry_after_header:
        try:
            return min(float(retry_after_header), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            try:
                dt = parsedate_to_datetime(retry_after_header)
            except (TypeError, ValueError):
                return None
            return min(max(0.0, (dt - datetime.now(UTC)).total_seconds()), MAX_RETRY_AFTER_SECONDS)

    reset_header = response.headers.get("X-Sentry-Rate-Limit-Reset")
    if reset_header:
        try:
            reset_epoch = int(reset_header)
        except ValueError:
            return None
        wait_seconds = reset_epoch - int(datetime.now(UTC).timestamp())
        if wait_seconds <= 0:
            return None
        return min(float(wait_seconds), MAX_RETRY_AFTER_SECONDS)

    return None


def _stop_after_client_attempts(state: RetryCallState) -> bool:
    # tenacity passes the wrapped call's positional args; for the bound
    # `_send_request(self, ...)` that's `(client, request, hooks)`, so the
    # attempt cap reads off the instance and the preview can lower it to 1.
    client = state.args[0] if state.args else None
    max_attempts = getattr(client, "_max_retry_attempts", DEFAULT_RETRY_ATTEMPTS)
    return state.attempt_number >= max_attempts


def _retry_wait_seconds(state: RetryCallState) -> float:
    fallback = min(2 ** (state.attempt_number - 1), 60)
    if state.outcome is None or not state.outcome.failed:
        return float(fallback)
    exc = state.outcome.exception()
    if isinstance(exc, RESTClientRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return float(fallback)


Hooks = dict[str, list[Any]]


def _body_shape_is_list(body: Any, data_selector: Optional[TJsonPath]) -> bool:
    """Whether ``body`` carries the expected list of rows once ``data_selector`` is applied.

    Mirrors ``_extract_response``'s shape rules: with a selector the key must be present and
    resolve to a list; without one the whole body must be a list. Used by the retryable-body
    check so a 200 whose payload is the wrong shape (a truncating proxy, a transient error
    envelope) is retried rather than failing loud or being silently ingested as a single row.
    """
    if data_selector:
        matches: Any = find_values(data_selector, body)
        if not matches:
            return False
        value = matches[0] if isinstance(matches, list) and len(matches) == 1 else matches
        return isinstance(value, list)
    return isinstance(body, list)


class RESTClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        auth: Optional[AuthBase] = None,
        paginator: Optional[BasePaginator] = None,
        session: Optional[Session] = None,
        max_retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        allowed_hosts: Optional[list[str]] = None,
        allow_redirects: bool = True,
    ) -> None:
        self.base_url = base_url or ""
        self.headers = headers or {}
        self.auth = auth
        self.paginator = paginator
        self._max_retry_attempts = max_retry_attempts
        self._allow_redirects = allow_redirects
        # When set (even to an empty list), every outgoing request URL — including
        # paginator next-page links and seeded resume URLs — must resolve to one of
        # these hosts (the base_url host is always implicitly allowed). This pins
        # pagination to the expected host so a tampered or spoofed ``next`` link can't
        # exfiltrate the Authorization header to an attacker-controlled origin. Pair
        # with ``allow_redirects=False`` to also reject cross-host redirects.
        self._allowed_hosts: Optional[set[str]] = None
        if allowed_hosts is not None:
            hosts = {host.lower() for host in allowed_hosts if host}
            base_host = urlsplit(self.base_url).hostname
            if base_host:
                hosts.add(base_host.lower())
            self._allowed_hosts = hosts
        # The auth's credential values, kept for value-based redaction. They feed both the
        # tracked session's log redaction AND ``_redact`` below, which scrubs them from raised
        # exception messages — an API that carries its key in a query param would otherwise leak
        # it via the request URL embedded in ``raise_for_status`` / ``HTTP {status} for {url}``.
        self._redact_values = tuple(value for value in auth_secret_values(auth) if value)
        # Default to the tracked session so every source built on top of
        # `RESTClient` participates in HTTP logging, metrics, and sample
        # capture. Callers can pass a pre-built `Session` for tests or
        # specialized auth (it should still be a tracked one in prod).
        self.session = session or make_tracked_session(redact_values=self._redact_values)
        if self.headers:
            self.session.headers.update(self.headers)

    def _join_url(self, path: str) -> str:
        return resolve_request_url(self.base_url, path)

    def _redact(self, text: str) -> str:
        for secret in self._redact_values:
            text = text.replace(secret, "***")
        return text

    def _check_allowed_host(self, url: Optional[str]) -> None:
        if self._allowed_hosts is None or not url:
            return
        host = urlsplit(url).hostname
        if host is None or host.lower() not in self._allowed_hosts:
            raise ValueError(
                self._redact(
                    f"Refusing to send request to disallowed host {host!r} (url {url!r}); "
                    f"allowed hosts: {sorted(self._allowed_hosts)}. A pagination or resume URL "
                    "pointing off the expected API host is rejected to prevent credential exfiltration."
                )
            )

    def paginate(
        self,
        path: str = "",
        method: str = "get",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        paginator: Optional[BasePaginator] = None,
        data_selector: Optional[TJsonPath] = None,
        hooks: Optional[Hooks] = None,
        resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
        initial_paginator_state: Optional[dict[str, Any]] = None,
        data_selector_required: bool = False,
        data_selector_malformed_retryable: bool = False,
    ) -> Iterator[list[Any]]:
        paginator = copy.deepcopy(paginator) if paginator else copy.deepcopy(self.paginator)
        hooks = hooks or {}

        # When set, a 200 whose parsed body isn't the expected list shape is RETRIED (not failed
        # loud): the check runs inside the retry-wrapped ``_send_request`` so a transient malformed
        # payload is reissued. This reproduces sources that defensively classify an unexpected
        # 200-body shape as retryable. Distinct from ``data_selector_required`` (permanent fail-loud).
        malformed_check: Optional[Callable[[Any], None]] = None
        if data_selector_malformed_retryable:

            def malformed_check(body: Any) -> None:
                if not _body_shape_is_list(body, data_selector):
                    raise RESTClientRetryableError("Unexpected 200 response body shape (expected a list of rows)")

        # `requests` serializes None values as the literal string "None" in the
        # query string — drop them so optional/incremental params that are not
        # set don't leak into the URL.
        request_params = {key: value for key, value in (params or {}).items() if value is not None}

        request = Request(
            method=method.upper(),
            url=self._join_url(path),
            params=request_params,
            json=json,
            auth=self.auth,
        )

        if paginator:
            if initial_paginator_state is not None:
                paginator.set_resume_state(initial_paginator_state)
            paginator.init_request(request)

        while True:
            try:
                response, body = self._send_request(request, hooks, body_check=malformed_check)
            except IgnoreResponseException:
                break

            data = self._extract_response(body, data_selector, required=data_selector_required)

            if paginator is not None:
                paginator.update_state(response, data)
                paginator.update_request(request)

            yield data

            if resume_hook is not None:
                resume_hook(paginator.get_resume_state() if paginator is not None and paginator.has_next_page else None)

            if paginator is None or not paginator.has_next_page:
                break

    @retry(
        retry=retry_if_exception_type(RESTClientRetryableError),
        stop=_stop_after_client_attempts,
        wait=_retry_wait_seconds,
        reraise=True,
    )
    def _send_request(
        self, request: Request, hooks: Hooks, body_check: Optional[Callable[[Any], None]] = None
    ) -> tuple[Response, Any]:
        prepared = self.session.prepare_request(request)
        # Fail loud on a pagination/resume URL that points off the expected host before the
        # request (and its Authorization header) ever leaves the process. Raised outside the
        # retryable-error type so it propagates immediately rather than being retried.
        self._check_allowed_host(prepared.url)
        # `send` reads the body eagerly (stream=False), so a connection dropped mid-stream
        # surfaces here as ChunkedEncodingError. Reissue it like a truncated/partial body below.
        try:
            response = self.session.send(prepared, allow_redirects=self._allow_redirects)
        except ChunkedEncodingError as e:
            raise RESTClientRetryableError(self._redact(f"Connection broken while reading response: {e}")) from e

        # With redirects disabled, a 3xx is not an error to `raise_for_status` and would fall
        # through to JSON parsing; reject it explicitly so a redirect can't smuggle the request
        # (and credentials) to another origin.
        if not self._allow_redirects and response.is_redirect:
            raise ValueError(
                self._redact(
                    f"Unexpected redirect ({response.status_code}) to "
                    f"{response.headers.get('Location')!r} from {prepared.url}; refusing to follow."
                )
            )

        if response.status_code == 429 or response.status_code >= 500:
            raise RESTClientRetryableError(
                self._redact(f"HTTP {response.status_code} for {response.url}"),
                retry_after=_parse_retry_after(response),
            )

        response_hooks = hooks.get("response", [])
        if response_hooks:
            for hook in response_hooks:
                hook(response, request=request)
        else:
            # Redact any secret the URL carries (e.g. an api_key query param) out of the raised
            # HTTPError message before it propagates into a user-visible ``latest_error``.
            try:
                response.raise_for_status()
            except HTTPError as e:
                raise HTTPError(self._redact(str(e)), response=e.response, request=e.request) from None

        # Parse inside the retry so a truncated/partial body is reissued like a 429/5xx
        # instead of bubbling up uncaught and failing the import.
        try:
            body = response.json()
        except RequestsJSONDecodeError as e:
            # An empty body on an otherwise-successful response is a complete "no data"
            # answer (e.g. an endpoint with nothing to return), not a truncated page —
            # retrying can't conjure rows, so treat it as an empty page and let the
            # paginator stop. A non-empty body that fails to parse is a partial/truncated
            # read, which stays retryable.
            if not response.content or not response.content.strip():
                return response, None
            raise RESTClientRetryableError(self._redact(f"Malformed JSON response from {response.url}: {e}")) from e

        # Runs inside the retry loop so an unexpected-but-parseable 200 body (wrong shape) can be
        # reissued as retryable rather than surfacing as a permanent error or a garbage row.
        if body_check is not None and body is not None:
            body_check(body)

        return response, body

    def _extract_response(self, body: Any, data_selector: Optional[TJsonPath], *, required: bool = False) -> list[Any]:
        if data_selector:
            matches: Any = find_values(data_selector, body)
            # ``required`` distinguishes "the selector key is absent" (no matches -> the response
            # shape changed, fail loud) from "the key is present but the list is empty" (a legit
            # zero-row page, which yields one match whose value is []). Sources that treat a missing
            # data key as an error set data_selector_required=True instead of silently syncing 0 rows.
            if required and not matches:
                keys = sorted(body.keys())[:20] if isinstance(body, dict) else type(body).__name__
                raise ValueError(
                    f"Required data_selector {data_selector!r} matched nothing in the response "
                    f"(body keys: {keys}). The API response shape may have changed."
                )
            data: Any = matches
            # unwrap single-item list from jsonpath
            if isinstance(data, list) and len(data) == 1:
                data = data[0]
        else:
            # No selector: the whole body is the row list. With ``required``, a non-list body means
            # the response shape changed (e.g. an error object on a 200) — fail loud rather than
            # wrapping the stray object as a single row.
            if required and not isinstance(body, list):
                raise ValueError(
                    f"Required a list response body, got {type(body).__name__}. "
                    "The API response shape may have changed."
                )
            data = body

        if data is None:
            return []
        if not isinstance(data, list):
            data = [data]
        return data
