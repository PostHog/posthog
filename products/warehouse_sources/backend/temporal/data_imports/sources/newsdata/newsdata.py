import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.settings import (
    NEWSDATA_ENDPOINTS,
    NewsDataEndpointConfig,
)

NEWSDATA_BASE_URL = "https://newsdata.io/api/1"

# One request grabs a plan-limited page (10 free / 50 paid), so a page never approaches the batch
# size threshold — we accumulate several pages before handing a batch to the pipeline.
_BATCH_SIZE = 2000


class NewsDataRetryableError(Exception):
    """Raised for 429/5xx responses so tenacity retries with backoff."""


class NewsDataError(Exception):
    """Raised for permanent API failures (unsupported param, quota exhausted) that must not retry."""


@dataclasses.dataclass
class NewsDataResumeConfig:
    # Opaque `nextPage` cursor token to resume pagination from. None means "start at the first page".
    next_page: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    # NewsData accepts the key either as an `apikey` query param or the `X-ACCESS-KEY` header. We use
    # the header so the secret never lands in a logged request URL.
    return {"X-ACCESS-KEY": api_key, "Accept": "application/json"}


def _to_from_date(value: Any) -> str | None:
    """Reduce an incremental watermark to the `YYYY-MM-DD` string NewsData's `from_date` expects.

    The watermark comes back as a datetime (parsed by the pipeline), a date, or a raw string
    depending on how it was stored; NewsData's date filter is day-granular either way.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat() if value.tzinfo else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Fall back to the leading YYYY-MM-DD of a string like "2024-01-15 12:34:56".
    return str(value)[:10]


def _build_query_params(
    config: NewsDataEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Build the endpoint's query params (excluding the cursor, which is added per page).

    Only `from_date` is applied, and only for date-filter endpoints: on the first incremental sync
    it floors the crawl at a trailing lookback window, and on later syncs it advances from the stored
    watermark. Full-refresh endpoints send no params. `size` is intentionally omitted — the page size
    is plan-capped and passing an over-cap value 4xxs, so we let the API apply its own default.
    """
    if not (config.supports_date_filter and should_use_incremental_field):
        return {}

    from_date = _to_from_date(db_incremental_field_last_value)
    if from_date is None and config.default_lookback_days is not None:
        from_date = (datetime.now(UTC) - timedelta(days=config.default_lookback_days)).date().isoformat()

    return {"from_date": from_date} if from_date else {}


def _raise_for_error_body(payload: dict[str, Any], page_url: str) -> None:
    """NewsData signals problems in the body (`{"status": "error", "results": {...}}`).

    Retryable rate-limit errors still arrive as HTTP 429 and are handled in `_fetch_page`; anything
    left here (unsupported params, quota exhaustion) is a hard error worth surfacing.
    """
    if payload.get("status") == "error":
        results = payload.get("results")
        message = results.get("message") if isinstance(results, dict) else str(results)
        raise NewsDataError(f"NewsData API returned error status: {message} (url={page_url})")


@retry(
    retry=retry_if_exception_type(
        (
            NewsDataRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(page_url, headers=headers, timeout=60)

    # 429 (rate limit / daily credit throttle) and transient 5xx are retryable; everything else that
    # isn't ok is a permanent failure (bad key, unsupported param) raised via raise_for_status.
    if response.status_code == 429 or response.status_code >= 500:
        raise NewsDataRetryableError(f"NewsData API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        logger.error(f"NewsData API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # The sources catalog is the cheapest authenticated probe: no pagination, small body, and it only
    # needs a valid key. An invalid or missing key returns HTTP 401.
    url = f"{NEWSDATA_BASE_URL}/sources"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _page_url(config: NewsDataEndpointConfig, params: dict[str, str], next_page: str | None) -> str:
    page_params = dict(params)
    if next_page:
        page_params["page"] = next_page
    query = urlencode(page_params)
    base = f"{NEWSDATA_BASE_URL}{config.path}"
    return f"{base}?{query}" if query else base


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewsDataResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = NEWSDATA_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive between requests.
    # `redact_values` masks the API key anywhere it surfaces in logged/captured telemetry.
    session = make_tracked_session(redact_values=(api_key,))

    params = _build_query_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_page = resume.next_page if resume else None
    if next_page:
        logger.debug(f"NewsData: resuming {endpoint} from cursor")

    batch: list[dict[str, Any]] = []
    while True:
        url = _page_url(config, params, next_page)
        data = _fetch_page(session, url, headers, logger)
        _raise_for_error_body(data, url)

        results = data.get("results") or []
        batch.extend(results)

        # `nextPage` is an opaque cursor token; its absence (or a non-paginating endpoint) ends the walk.
        next_page = data.get("nextPage") if config.supports_pagination else None

        if len(batch) >= _BATCH_SIZE:
            yield batch
            batch = []
            # Save AFTER yielding so a crash re-yields the last batch (merge dedupes on the primary
            # key) rather than skipping it. Only persist when more pages remain.
            if next_page:
                resumable_source_manager.save_state(NewsDataResumeConfig(next_page=next_page))

        if not next_page:
            break

    if batch:
        yield batch


def newsdata_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewsDataResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NEWSDATA_ENDPOINTS[endpoint]

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
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
