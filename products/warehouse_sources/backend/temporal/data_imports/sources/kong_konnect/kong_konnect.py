import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.settings import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    KONG_KONNECT_ENDPOINTS,
    MAX_PAGE_SIZE,
    REGION_BASE_URLS,
)

REQUEST_TIMEOUT_SECONDS = 60


class KongKonnectRetryableError(Exception):
    pass


@dataclasses.dataclass
class KongKonnectResumeConfig:
    # Bounds of the absolute time window this run is paging through. Pinned in resume state so a resumed
    # attempt re-issues the identical window and its offset stays meaningful — recomputing `end` as
    # "now" on resume would shift the window and make the saved offset skip or duplicate rows.
    start: str | None = None
    end: str | None = None
    offset: int = 0


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as a UTC ISO 8601 timestamp for Konnect's absolute time_range bounds."""
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        # Already a string cursor — trust it as-is.
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future incremental cursor at now.

    The watermark tracks the max `request_start` seen. A future-dated record would push the window
    start past now, producing an empty (or rejected) window on every later sync. Requesting rows newer
    than now is a no-op anyway, so clamping keeps the query valid and lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _get_base_url(region: str) -> str:
    return REGION_BASE_URLS.get(region, REGION_BASE_URLS["us"])


def _get_headers(api_token: str) -> dict[str, str]:
    # Personal Access Tokens and System Account tokens are both bearer tokens sent identically.
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _resolve_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    lookback_days: int,
) -> tuple[str, str]:
    """Compute the [start, end] absolute window for this run.

    Incremental runs start at the watermark; first sync / full refresh walks back `lookback_days`.
    `end` is pinned to now so pagination through the window is stable.
    """
    now = datetime.now(UTC)
    if should_use_incremental_field and db_incremental_field_last_value:
        start_value = _clamp_future_value_to_now(db_incremental_field_last_value)
        start = _format_datetime(start_value)
    else:
        start = _format_datetime(now - timedelta(days=lookback_days))
    return start, _format_datetime(now)


def _build_body(start: str, end: str, offset: int, size: int) -> dict[str, Any]:
    return {
        "filters": [],
        "time_range": {
            "type": "absolute",
            "start": start,
            "end": end,
            "tz": "Etc/UTC",
        },
        # Ascending by time so SourceResponse.sort_mode="asc" lets the pipeline advance the watermark
        # after each batch and resume mid-sync safely.
        "order": "ascending",
        "size": size,
        "offset": offset,
    }


@retry(
    retry=retry_if_exception_type(
        (
            KongKonnectRetryableError,
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
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise KongKonnectRetryableError(f"Kong Konnect API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Kong Konnect API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str, region: str) -> bool:
    """Cheap probe that the bearer token is genuine: request a single record over a small window."""
    url = f"{_get_base_url(region)}/api-requests"
    body = _build_body(
        _format_datetime(datetime.now(UTC) - timedelta(hours=1)),
        _format_datetime(datetime.now(UTC)),
        offset=0,
        size=1,
    )
    try:
        response = make_tracked_session().post(url, headers=_get_headers(api_token), json=body, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    lookback_days: int = DEFAULT_INITIAL_LOOKBACK_DAYS,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{_get_base_url(region)}{KONG_KONNECT_ENDPOINTS[endpoint].path}"
    headers = _get_headers(api_token)
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.start and resume.end:
        start, end, offset = resume.start, resume.end, resume.offset
        logger.debug(f"Kong Konnect: resuming api_requests window start={start} end={end} offset={offset}")
    else:
        start, end = _resolve_window(should_use_incremental_field, db_incremental_field_last_value, lookback_days)
        offset = 0

    while True:
        body = _build_body(start, end, offset, MAX_PAGE_SIZE)
        data = _fetch_page(session, url, headers, body, logger)
        results = data.get("results", [])

        if not results:
            break

        yield results

        offset += len(results)
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on request_id) rather
        # than skipping it. Only persist when another page is likely, i.e. this page was full.
        if len(results) < MAX_PAGE_SIZE:
            break
        resumable_source_manager.save_state(KongKonnectResumeConfig(start=start, end=end, offset=offset))


def kong_konnect_source(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    lookback_days: int = DEFAULT_INITIAL_LOOKBACK_DAYS,
) -> SourceResponse:
    endpoint_config = KONG_KONNECT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            lookback_days=lookback_days,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
