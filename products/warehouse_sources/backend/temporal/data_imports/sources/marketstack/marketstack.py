import dataclasses
from collections.abc import Iterator
from datetime import date
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.settings import MARKETSTACK_ENDPOINTS

# Marketstack keeps two live API versions; v1 is stable, covers every endpoint we sync, and is
# available on the free plan. v2 only adds indices and the /latest lookups we don't use here.
MARKETSTACK_BASE_URL = "https://api.marketstack.com/v1"
# limit maxes out at 1000; larger pages mean fewer round trips against the 5 req/sec rate limit.
DEFAULT_PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Marketstack (an APILayer product) can return HTTP 200 with an error envelope
# (`{"error": {"code": ...}}`). Only genuinely transient codes are retried; every other code
# (bad/blocked key, plan gating, exhausted monthly quota) fails fast and is surfaced as a permanent
# failure matched by MarketstackSource.get_non_retryable_errors on the stable `[code]` token.
_RETRYABLE_ERROR_CODES = {"rate_limit_reached", "too_many_requests"}


class MarketstackRetryableError(Exception):
    pass


class MarketstackAPIError(Exception):
    pass


@dataclasses.dataclass
class MarketstackResumeConfig:
    # Offset of the next page to fetch — Marketstack uses limit/offset pagination.
    next_offset: int


def _format_date(value: Any) -> str:
    """Format an incremental cursor for the `date_from` filter (Marketstack expects YYYY-MM-DD)."""
    # datetime is a subclass of date, so this covers both.
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    # A stored string cursor is already an ISO timestamp/date — keep just the date portion.
    return str(value)[:10]


@retry(
    retry=retry_if_exception_type((MarketstackRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # `url` carries no secrets — the access_key lives in `params`, which requests keeps out of the
    # log line emitted here — so it's safe to log on error.
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise MarketstackRetryableError(f"Marketstack API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Marketstack API error: status={response.status_code}, url={url}")
        # Don't use `response.raise_for_status()` — it embeds `response.url` (which carries the
        # access_key query param) in the error message, and that exception is later logged via
        # `str(error)` outside the tracked session's redaction. Strip the query string instead.
        kind = "Client Error" if response.status_code < 500 else "Server Error"
        safe_url = response.url.split("?", 1)[0]
        raise requests.HTTPError(
            f"{response.status_code} {kind}: {response.reason} for url: {safe_url}", response=response
        )

    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    if error:
        code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        if code in _RETRYABLE_ERROR_CODES:
            raise MarketstackRetryableError(f"Marketstack API error (retryable) [{code}]: {message}")
        # Permanent codes (and anything unrecognized) fail fast — the keys in
        # get_non_retryable_errors match on the `[code]` token.
        raise MarketstackAPIError(f"Marketstack API error [{code}]: {message}")

    return body


def get_rows(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MarketstackResumeConfig],
    symbols: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[Any]:
    config = MARKETSTACK_ENDPOINTS[endpoint]
    url = f"{MARKETSTACK_BASE_URL}{config.path}"

    if config.requires_symbols and not (symbols and symbols.strip()):
        raise MarketstackAPIError(
            f"Marketstack API error [missing_symbols]: the '{endpoint}' table requires one or more "
            "symbols. Add symbols to the source configuration, then resync."
        )

    # `access_key` is passed as a query param on every request, so mask its value from the
    # tracked session's logged URLs and captured samples.
    session = make_tracked_session(redact_values=(access_key,))
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    base_params: dict[str, Any] = {"access_key": access_key, "limit": page_size}
    if config.requires_symbols and symbols:
        base_params["symbols"] = symbols
    if config.incremental_fields:
        # Ascending sort keeps rows in date order so the pipeline watermark advances correctly; it's
        # also required for date_from windowing to line up with SourceResponse.sort_mode="asc".
        base_params["sort"] = "ASC"
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            base_params["date_from"] = _format_date(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.next_offset if resume is not None else 0
    if resume is not None:
        logger.debug(f"Marketstack: resuming {endpoint} from offset={offset}")

    while True:
        body = _fetch_page(session, url, {**base_params, "offset": offset}, logger)

        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list):
            items = []

        pagination = body.get("pagination") if isinstance(body, dict) else None
        total = pagination.get("total") if isinstance(pagination, dict) else None

        next_offset = offset + page_size
        has_more = len(items) >= page_size and (not isinstance(total, int) or next_offset < total)

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
                # page rather than skipping it — merge/replace dedupes the re-pulled rows.
                if has_more:
                    resumable_source_manager.save_state(MarketstackResumeConfig(next_offset=next_offset))

        if not has_more:
            break
        offset = next_offset

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def marketstack_source(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MarketstackResumeConfig],
    symbols: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MARKETSTACK_ENDPOINTS[endpoint]

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_key=access_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            symbols=symbols,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # We always request `sort=ASC` on the time-series feeds and reference tables are unordered
        # full refreshes, so ascending is safe across the board.
        sort_mode="asc",
        **partition_kwargs,
    )


def validate_credentials(access_key: str) -> bool:
    # `/exchanges` is a static reference endpoint available on every plan (including free) and needs
    # no symbols, so it's a cheap probe that the access key is genuine.
    url = f"{MARKETSTACK_BASE_URL}/exchanges"
    params: dict[str, Any] = {"access_key": access_key, "limit": 1}
    try:
        session = make_tracked_session(redact_values=(access_key,))
        response = session.get(url, params=params, timeout=10)
    except Exception:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return not (isinstance(body, dict) and bool(body.get("error")))
