import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.settings import (
    OURA_ENDPOINTS,
    OuraEndpointConfig,
)

OURA_BASE_URL = "https://api.ouraring.com/v2"

# Oura rings didn't exist before 2015; this lower bound guarantees a full backfill on first sync.
# The API defaults start_date to end_date - 1 day, so an explicit early start is required to pull
# history rather than just the most recent day.
DEFAULT_START_DATE = "2014-01-01"

PAGE_TIMEOUT_SECONDS = 60
VALIDATE_TIMEOUT_SECONDS = 10


class OuraRetryableError(Exception):
    pass


@dataclasses.dataclass
class OuraResumeConfig:
    # Opaque pagination cursor returned by the API as `next_token`. Resuming re-issues the same
    # date-windowed request with this token appended.
    next_token: str | None = None


def _get_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _format_date(value: Any) -> str:
    """Format a date cursor value as the YYYY-MM-DD string Oura's start_date expects."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Stored cursor can come back as an ISO string; the date component is the first 10 chars.
    return str(value)[:10]


def _format_datetime(value: Any) -> str:
    """Format a datetime cursor value as the ISO 8601 string Oura's start_datetime expects."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _clamp_date_to_today(value: str) -> str:
    """Cap a start_date at today. A future-dated record can push the cursor past today, and Oura
    400s when start_date is after end_date (which defaults to today)."""
    today = datetime.now(UTC).date().isoformat()
    return today if value > today else value


def _clamp_datetime_to_now(value: str) -> str:
    now = datetime.now(UTC).isoformat()
    return now if value > now else value


def _build_initial_params(
    config: OuraEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Build the date-window query params for the first page of a request."""
    params: dict[str, str] = {}

    have_cursor = should_use_incremental_field and db_incremental_field_last_value is not None

    if config.date_filter == "date":
        start = _format_date(db_incremental_field_last_value) if have_cursor else DEFAULT_START_DATE
        params["start_date"] = _clamp_date_to_today(start)
    elif config.date_filter == "datetime":
        if have_cursor:
            start = _clamp_datetime_to_now(_format_datetime(db_incremental_field_last_value))
        else:
            start = f"{DEFAULT_START_DATE}T00:00:00+00:00"
        params["start_datetime"] = start

    return params


def _build_url(path: str, params: dict[str, str]) -> str:
    url = f"{OURA_BASE_URL}{path}"
    if params:
        return f"{url}?{urlencode(params)}"
    return url


@retry(
    retry=retry_if_exception_type((OuraRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=PAGE_TIMEOUT_SECONDS)

    # Oura rate-limits at ~5000 requests / 5 min and returns 429 with backoff expected.
    if response.status_code == 429 or response.status_code >= 500:
        raise OuraRetryableError(f"Oura API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Oura API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def probe_endpoint(token: str, path: str) -> int:
    """Return the HTTP status code for a minimal GET against `path`. -1 on a transport failure."""
    try:
        response = make_tracked_session().get(
            f"{OURA_BASE_URL}{path}", headers=_get_headers(token), timeout=VALIDATE_TIMEOUT_SECONDS
        )
        return response.status_code
    except Exception:
        return -1


def get_rows(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OuraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = OURA_ENDPOINTS[endpoint]
    headers = _get_headers(token)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    # Single-document endpoints (e.g. personal_info) return a flat object, not a
    # {data: [...], next_token} envelope.
    if config.is_single_document:
        document = _fetch_page(session, _build_url(config.path, {}), headers, logger)
        yield [document]
        return

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_token:
        params = {**params, "next_token": resume.next_token}
        logger.debug(f"Oura: resuming {endpoint} from next_token")

    while True:
        data = _fetch_page(session, _build_url(config.path, params), headers, logger)

        # Use `data["data"]` (not `.get`) so an unexpected 200 without the documented envelope
        # raises a KeyError and fails the sync loudly, rather than silently ingesting zero rows.
        items = data["data"]
        next_token = data.get("next_token")

        if items:
            yield items

        if not next_token:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes on the primary key. Advance the cursor before the next fetch to avoid re-looping
        # the same page.
        resumable_source_manager.save_state(OuraResumeConfig(next_token=next_token))
        params = {**params, "next_token": next_token}


def oura_source(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OuraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OURA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            token=token,
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
        # Oura returns records in ascending date order; we additionally re-window by start_date on
        # every sync, so the checkpointed watermark advances correctly.
        sort_mode="asc",
    )
