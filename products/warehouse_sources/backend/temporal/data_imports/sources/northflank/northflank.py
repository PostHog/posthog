from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.settings import NORTHFLANK_ENDPOINTS

NORTHFLANK_BASE_URL = "https://api.northflank.com"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Northflank paginates at up to 100 results per page (defaults to 50 if unset).
PAGE_SIZE = 100
# Guardrails against an unbounded scan. The 1000 req/hour account rate limit makes deep fan-out
# expensive, so bound both the project scan and each project's child scan by pages.
MAX_PROJECT_PAGES = 500
MAX_CHILD_PAGES_PER_PROJECT = 500
# The API asks us to wait via rate-limit headers on a 429; clamp anything absurd.
MAX_RATE_LIMIT_SLEEP_SECONDS = 120


class NorthflankRetryableError(Exception):
    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        # Seconds the API asked us to wait (from Retry-After/x-ratelimit-reset); 0 when unknown.
        self.retry_after = retry_after


FetchPageFn = Callable[[str], dict[str, Any]]

_EXPONENTIAL_WAIT = wait_exponential_jitter(initial=1, max=60)


def _retry_wait(retry_state: RetryCallState) -> float:
    # Honor the API's reset hint once; otherwise back off exponentially. Doing the wait here (rather
    # than sleeping inside fetch_page) avoids stacking both delays.
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, NorthflankRetryableError) and exc.retry_after:
        return exc.retry_after
    return _EXPONENTIAL_WAIT(retry_state)


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    clean_params = {key: value for key, value in (params or {}).items() if value is not None}
    if not clean_params:
        return f"{NORTHFLANK_BASE_URL}{path}"
    return f"{NORTHFLANK_BASE_URL}{path}?{urlencode(clean_params)}"


def _rate_limit_sleep_seconds(response: requests.Response) -> int:
    # `x-ratelimit-reset` is documented as time-to-reset in seconds; prefer a Retry-After if present.
    for header in ("retry-after", "x-ratelimit-reset"):
        raw = response.headers.get(header)
        if raw is None:
            continue
        try:
            seconds = int(float(raw))
        except (TypeError, ValueError):
            continue
        return max(0, min(seconds, MAX_RATE_LIMIT_SLEEP_SECONDS))
    return 0


def _extract_rows(body: dict[str, Any], data_key: str) -> list[dict[str, Any]]:
    """Pull the row array out of Northflank's `{"data": {...}}` envelope.

    List endpoints nest the array under `data.<resource>` (e.g. `data.projects`). We also tolerate
    `data` being the array itself, since the API reference is inconsistent on this for some
    endpoints and we can't curl-verify every one.
    """
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get(data_key)
        if isinstance(rows, list):
            return rows
    return []


def _next_cursor(body: dict[str, Any]) -> str | None:
    pagination = body.get("pagination") or {}
    if not pagination.get("hasNextPage"):
        return None
    return pagination.get("cursor")


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the token by listing projects (the resource every stream depends on)."""
    # Disable the adapter's urllib3 retry layer: an already rate-limited token would otherwise make
    # validation block the worker for the provider's full (uncapped) Retry-After. Fail fast instead.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_token,))
    try:
        response = session.get(
            _build_url("/v1/projects", {"per_page": 1}),
            headers=_get_headers(api_token),
            timeout=10,
        )
    except Exception:
        return False, "Could not reach the Northflank API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Northflank API token. Please check that your token is valid and not revoked."
    return False, f"Northflank API returned an unexpected status: {response.status_code}."


def _make_fetch_page(api_token: str, logger: FilteringBoundLogger) -> FetchPageFn:
    headers = _get_headers(api_token)
    # One session reused across pages/retries so connection pooling and per-session tracking hold;
    # redact_values masks the token in logs and captured samples. retry=Retry(total=0) disables the
    # adapter's urllib3 retry layer so the tenacity policy below is the only one — otherwise urllib3
    # would retry 429/5xx underneath it, honoring an uncapped Retry-After and stacking retry layers,
    # bypassing this connector's capped rate-limit backoff.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_token,))

    @retry(
        retry=retry_if_exception_type((NorthflankRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(url: str) -> dict[str, Any]:
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429:
            sleep_seconds = _rate_limit_sleep_seconds(response)
            logger.debug(f"Northflank: rate limited, retrying after {sleep_seconds}s. url={url}")
            raise NorthflankRetryableError(
                f"Northflank API rate limited: status=429, url={url}", retry_after=sleep_seconds
            )

        if response.status_code >= 500:
            raise NorthflankRetryableError(
                f"Northflank API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Northflank API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def _iter_pages(
    fetch_page: FetchPageFn,
    path: str,
    logger: FilteringBoundLogger,
    max_pages: int,
    resource: str,
    data_key: str,
) -> Iterator[list[dict[str, Any]]]:
    """Yield each page's rows for a cursor-paginated list endpoint."""
    cursor: str | None = None
    pages_fetched = 0

    while True:
        params = {"per_page": PAGE_SIZE, "cursor": cursor}
        body = fetch_page(_build_url(path, params))
        pages_fetched += 1

        rows = _extract_rows(body, data_key)
        if rows:
            yield rows

        cursor = _next_cursor(body)
        if not cursor:
            return

        if pages_fetched >= max_pages:
            logger.warning(
                f"Northflank: page cap reached for {resource}, stopping pagination. max_pages={max_pages}, path={path}"
            )
            return


def _iter_project_ids(fetch_page: FetchPageFn, logger: FilteringBoundLogger) -> Iterator[str]:
    for projects in _iter_pages(
        fetch_page, "/v1/projects", logger, max_pages=MAX_PROJECT_PAGES, resource="projects", data_key="projects"
    ):
        for project in projects:
            project_id = project.get("id")
            if not project_id:
                # A project without an id would silently drop all of its nested resources
                # (services, jobs, addons, volumes), leaving a partial import. Fail loudly instead.
                raise ValueError(f"Northflank: project is missing a required 'id' field: {project!r}")
            yield project_id


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in NORTHFLANK_ENDPOINTS:
        raise ValueError(f"Unknown Northflank endpoint: {endpoint}")

    config = NORTHFLANK_ENDPOINTS[endpoint]
    fetch_page = _make_fetch_page(api_token, logger)

    if not config.fan_out_over_projects:
        yield from _iter_pages(
            fetch_page,
            config.path,
            logger,
            max_pages=MAX_PROJECT_PAGES,
            resource=endpoint,
            data_key=config.data_key,
        )
        return

    for project_id in _iter_project_ids(fetch_page, logger):
        path = config.path.format(project_id=project_id)
        for rows in _iter_pages(
            fetch_page,
            path,
            logger,
            max_pages=MAX_CHILD_PAGES_PER_PROJECT,
            resource=f"{endpoint} of project {project_id}",
            data_key=config.data_key,
        ):
            # Inject the parent project id so the composite primary key is present even on child
            # objects that don't carry it natively (addons, volumes).
            yield [{**row, "projectId": project_id} for row in rows]


def northflank_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = NORTHFLANK_ENDPOINTS[endpoint]
    partition_key: Optional[str] = config.partition_key

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_token=api_token, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
