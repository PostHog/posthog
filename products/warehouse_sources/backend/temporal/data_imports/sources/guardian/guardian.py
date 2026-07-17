import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.settings import (
    GUARDIAN_ENDPOINTS,
    GuardianEndpointConfig,
)

GUARDIAN_BASE_URL = "https://content.guardianapis.com"

# The free developer tier caps page-size at 200; larger values are rejected.
PAGE_SIZE = 200

REQUEST_TIMEOUT_SECONDS = 60


class GuardianRetryableError(Exception):
    pass


@dataclasses.dataclass
class GuardianResumeConfig:
    # The next page number to fetch. The API is 1-indexed. With `order-by=oldest` the result set is
    # ordered ascending and stable within a run, so a page number is a safe resume cursor.
    page: int = 1


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _format_from_date(value: Any) -> str | None:
    """Map the incremental cursor to the API's day-granular `from-date` (YYYY-MM-DD).

    The Guardian only filters by calendar date, not by time, so an incremental sync re-fetches the
    watermark day. Those re-pulled rows dedupe on the `id` primary key at merge time.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        # Cursor persisted as an ISO string (e.g. "2026-07-02T13:12:10Z"); keep the date part.
        return value[:10]
    return None


def _build_base_params(
    config: GuardianEndpointConfig,
    api_key: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    params: dict[str, str] = {
        "api-key": api_key,
        "page-size": str(PAGE_SIZE),
        "format": "json",
        **config.extra_params,
    }

    if config.supports_incremental and should_use_incremental_field:
        from_date = _format_from_date(db_incremental_field_last_value)
        if from_date:
            params["from-date"] = from_date

    return params


def _build_url(path: str, params: dict[str, str]) -> str:
    return f"{GUARDIAN_BASE_URL}{path}?{urlencode(params)}"


def _scrub_url(url: str | None) -> str:
    # The api-key rides in the query string, so strip the query before the URL reaches any error
    # message or log line — otherwise a non-2xx response would leak the credential into job errors.
    if not url:
        return GUARDIAN_BASE_URL
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


@retry(
    retry=retry_if_exception_type(
        (
            GuardianRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit — the free tier caps ~12 req/s and a daily quota) and 5xx are transient.
    if response.status_code == 429 or response.status_code >= 500:
        raise GuardianRetryableError(f"Guardian API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Guardian API error: status={response.status_code}, body={response.text}, url={_scrub_url(url)}")
        # Raise with the api-key scrubbed from the URL rather than calling raise_for_status(), whose
        # message embeds the full credential-bearing URL. The base host stays intact so
        # `get_non_retryable_errors()` can still match on it.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {_scrub_url(response.url)}",
            response=response,
        )

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # /sections is a cheap, single-response endpoint — a genuine key returns 200, a bad one 401.
    url = _build_url("/sections", {"api-key": api_key, "page-size": "1"})
    try:
        # The api-key rides in the query string, so redact it from logged URLs and captured samples.
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_headers(), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GuardianResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GUARDIAN_ENDPOINTS[endpoint]
    # One session reused across pages so urllib3 keeps the connection alive. The api-key lives in the
    # query string, so redact it from logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_key,))

    base_params = _build_base_params(config, api_key, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume else 1

    while True:
        url = _build_url(config.path, {**base_params, "page": str(page)})
        response = _fetch_page(session, url, logger)["response"]

        results = response.get("results", [])
        if results:
            yield results

        # `sections` / `editions` return every row in one response with no pagination metadata,
        # so default to a single page. `search` / `tags` report `pages` and `currentPage`.
        total_pages = response.get("pages", 1)
        current_page = response.get("currentPage", page)
        if current_page >= total_pages:
            break

        page = current_page + 1
        # Save AFTER yielding so a crash re-fetches (and merge-dedupes) the last page rather than
        # skipping it. We persist the next page to fetch.
        resumable_source_manager.save_state(GuardianResumeConfig(page=page))


def guardian_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GuardianResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GUARDIAN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Only `content` guarantees an order: `order-by=oldest` returns ascending `webPublicationDate`,
        # matching the watermark direction. The full-refresh reference endpoints have no `order-by`, so
        # their row order is unspecified — leave `sort_mode` unset rather than claim ascending.
        sort_mode="asc" if config.supports_incremental else None,
    )
