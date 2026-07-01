import copy
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from requests import Request, Response, Session
from requests.auth import AuthBase
from requests.exceptions import (
    ChunkedEncodingError,
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


class RESTClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        auth: Optional[AuthBase] = None,
        paginator: Optional[BasePaginator] = None,
        session: Optional[Session] = None,
        max_retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    ) -> None:
        self.base_url = base_url or ""
        self.headers = headers or {}
        self.auth = auth
        self.paginator = paginator
        self._max_retry_attempts = max_retry_attempts
        # Default to the tracked session so every source built on top of
        # `RESTClient` participates in HTTP logging, metrics, and sample
        # capture. Callers can pass a pre-built `Session` for tests or
        # specialized auth (it should still be a tracked one in prod).
        # The auth's credential values are registered for value-based redaction
        # so a key injected into a query param/custom header can't leak into logs.
        self.session = session or make_tracked_session(redact_values=auth_secret_values(auth))
        if self.headers:
            self.session.headers.update(self.headers)

    def _join_url(self, path: str) -> str:
        return resolve_request_url(self.base_url, path)

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
    ) -> Iterator[list[Any]]:
        paginator = copy.deepcopy(paginator) if paginator else copy.deepcopy(self.paginator)
        hooks = hooks or {}

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
                response, body = self._send_request(request, hooks)
            except IgnoreResponseException:
                break

            data = self._extract_response(body, data_selector)

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
    def _send_request(self, request: Request, hooks: Hooks) -> tuple[Response, Any]:
        prepared = self.session.prepare_request(request)
        # `send` reads the body eagerly (stream=False), so a connection dropped mid-stream
        # surfaces here as ChunkedEncodingError. Reissue it like a truncated/partial body below.
        try:
            response = self.session.send(prepared)
        except ChunkedEncodingError as e:
            raise RESTClientRetryableError(f"Connection broken while reading response: {e}") from e

        if response.status_code == 429 or response.status_code >= 500:
            raise RESTClientRetryableError(
                f"HTTP {response.status_code} for {response.url}",
                retry_after=_parse_retry_after(response),
            )

        response_hooks = hooks.get("response", [])
        if response_hooks:
            for hook in response_hooks:
                hook(response, request=request)
        else:
            response.raise_for_status()

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
            raise RESTClientRetryableError(f"Malformed JSON response from {response.url}: {e}") from e

        return response, body

    def _extract_response(self, body: Any, data_selector: Optional[TJsonPath]) -> list[Any]:
        if data_selector:
            data: Any = find_values(data_selector, body)
            # unwrap single-item list from jsonpath
            if isinstance(data, list) and len(data) == 1:
                data = data[0]
        else:
            data = body

        if data is None:
            return []
        if not isinstance(data, list):
            data = [data]
        return data
