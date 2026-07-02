import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.settings import (
    NEW_YORK_TIMES_ENDPOINTS,
    NewYorkTimesEndpointConfig,
)

NEW_YORK_TIMES_BASE_URL = "https://api.nytimes.com"

# Article Search returns 10 results per page and hard-caps at 100 pages (1000 results) per query.
ARTICLE_SEARCH_PAGE_SIZE = 10
ARTICLE_SEARCH_MAX_PAGES = 100

# NYT rate limits are tight (≈10 requests/minute) and Article Search 429s aggressively. NYT explicitly
# recommends sleeping several seconds between calls, so we throttle paging politely and let the retry
# handler absorb any 429s that still slip through.
ARTICLE_SEARCH_PAGE_DELAY_SECONDS = 6.0


class NewYorkTimesRetryableError(Exception):
    pass


@dataclasses.dataclass
class NewYorkTimesResumeConfig:
    # Zero-based Article Search page index to fetch next. Snapshot endpoints never populate this.
    page: int = 0
    # The begin_date (YYYYMMDD) window this run is paging through. Persisted so a resume continues the
    # exact same window rather than recomputing `now - lookback`, which would drift over a long sync.
    begin_date: str | None = None


def _get_headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _format_begin_date(value: Any) -> str:
    """Format an incremental cursor value as the YYYYMMDD string Article Search's begin_date expects."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y%m%d") if value.tzinfo else value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    # A pre-formatted string cursor — trust it as-is.
    return str(value)


def _resolve_begin_date(
    config: NewYorkTimesEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str | None:
    """Pick the begin_date window for an Article Search run.

    Uses the incremental watermark when we have one, otherwise falls back to a recent lookback window so
    the first sync (and full refreshes) stay inside NYT's 1000-result cap instead of trying to page all
    of history back to 1851.
    """
    if should_use_incremental_field and db_incremental_field_last_value:
        return _format_begin_date(db_incremental_field_last_value)
    if config.default_lookback_days is not None:
        return (datetime.now(UTC) - timedelta(days=config.default_lookback_days)).strftime("%Y%m%d")
    return None


def _build_url(path: str, api_key: str, params: dict[str, Any]) -> str:
    query = {**params, "api-key": api_key}
    return f"{NEW_YORK_TIMES_BASE_URL}{path}?{urlencode(query)}"


def _sanitize_url(url: str) -> str:
    """Drop the query string so the api-key (passed as a query param) never lands in logs or errors."""
    return url.split("?", 1)[0]


@retry(
    retry=retry_if_exception_type(
        (
            NewYorkTimesRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise NewYorkTimesRetryableError(f"New York Times API error (retryable): status={response.status_code}")

    if not response.ok:
        # The api-key rides in the query string, so never surface the raw URL. Raise an HTTPError whose
        # message matches the non-retryable-error keys (status + base host) without leaking the key.
        safe_url = _sanitize_url(url)
        logger.error(f"New York Times API error: status={response.status_code}, url={safe_url}")
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe_url}", response=response
        )

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # Probe a cheap endpoint. A 401 means the key itself is bad or missing; anything else — including a
    # 403 from an app that has this particular API disabled — means the key is genuine. Users may enable
    # only the APIs they intend to sync, so a 403 must not block source creation.
    url = _build_url("/svc/mostpopular/v2/viewed/1.json", api_key, {})
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(), timeout=10)
        return response.status_code != 401
    except Exception:
        return False


def _select_rows(config: NewYorkTimesEndpointConfig, data: dict[str, Any]) -> list[dict[str, Any]]:
    if config.paginated:
        # Article Search nests its docs under `response`.
        return data.get("response", {}).get(config.data_selector, []) or []
    return data.get(config.data_selector, []) or []


def _get_snapshot_rows(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = _build_url(config.path, api_key, {})
    data = _fetch_page(session, url, _get_headers(), logger)
    rows = _select_rows(config, data)
    if rows:
        yield rows


def _get_article_search_rows(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    query: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    begin_date: str | None
    if resume is not None and resume.begin_date is not None:
        begin_date = resume.begin_date
        page = resume.page
        logger.debug(f"New York Times: resuming article_search from page={page}, begin_date={begin_date}")
    else:
        begin_date = _resolve_begin_date(config, should_use_incremental_field, db_incremental_field_last_value)
        page = 0

    while page < ARTICLE_SEARCH_MAX_PAGES:
        params: dict[str, Any] = {"page": page, "sort": "oldest"}
        if begin_date:
            params["begin_date"] = begin_date
        if query:
            params["q"] = query

        url = _build_url(config.path, api_key, params)
        data = _fetch_page(session, url, _get_headers(), logger)
        rows = _select_rows(config, data)

        if not rows:
            break

        yield rows

        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge dedupes
        # on `_id`.
        resumable_source_manager.save_state(NewYorkTimesResumeConfig(page=page, begin_date=begin_date))

        if len(rows) < ARTICLE_SEARCH_PAGE_SIZE:
            break

        if page >= ARTICLE_SEARCH_MAX_PAGES:
            logger.info(
                "New York Times: article_search hit the 100-page (1000-result) cap; remaining results in "
                "this window will be picked up by the next incremental sync"
            )
            break

        time.sleep(ARTICLE_SEARCH_PAGE_DELAY_SECONDS)


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    query: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = NEW_YORK_TIMES_ENDPOINTS[endpoint]
    # Redact the api-key (carried as a query param) from the tracked transport's logged URLs.
    session = make_tracked_session(redact_values=(api_key,))

    if config.paginated:
        yield from _get_article_search_rows(
            session,
            config,
            api_key,
            logger,
            resumable_source_manager,
            query,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _get_snapshot_rows(session, config, api_key, logger)


def new_york_times_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    query: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = NEW_YORK_TIMES_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            query=query,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Article Search is paged sort=oldest (ascending pub_date); snapshots are single-batch so order is
        # immaterial. Ascending keeps the incremental watermark advancing correctly.
        sort_mode="asc",
    )
