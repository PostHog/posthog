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
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.settings import (
    LEMLIST_ENDPOINTS,
    LemlistEndpointConfig,
)

LEMLIST_BASE_URL = "https://api.lemlist.com/api"
# lemlist caps list pages at 100 rows and rate-limits to 20 requests / 2s per API key.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class LemlistRetryableError(Exception):
    pass


@dataclasses.dataclass
class LemlistResumeConfig:
    # Offset of the next page to fetch. lemlist uses limit/offset pagination, so a single integer
    # is enough to pick back up where a crashed run left off.
    offset: int = 0


def _format_datetime_z(value: datetime) -> str:
    """ISO 8601 with a Z suffix — one of the two formats lemlist accepts for minDate/maxDate."""
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future cursor at now.

    The watermark tracks the max createdAt seen. A future-dated activity would otherwise push the
    cursor past now, and every later sync would ask for activities newer than the future — a no-op
    that just risks tripping lemlist's "maxDate must be greater than minDate" style validation.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_params(
    config: LemlistEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.requires_version_v2:
        params["version"] = "v2"

    if config.request_sort_by:
        params["sortBy"] = config.request_sort_by
    if config.request_sort_order:
        params["sortOrder"] = config.request_sort_order

    if config.supports_incremental and should_use_incremental_field:
        floor = db_incremental_field_last_value
        if floor is None and config.default_lookback_days:
            floor = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        if floor is not None:
            params["minDate"] = _format_incremental_value(_clamp_future_value_to_now(floor))

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{LEMLIST_BASE_URL}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((LemlistRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session, url: str, api_key: str, logger: FilteringBoundLogger
) -> list[dict[str, Any]] | dict[str, Any]:
    # lemlist uses HTTP Basic auth with an empty username and the API key as the password.
    response = session.get(url, auth=("", api_key), timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise LemlistRetryableError(f"lemlist API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"lemlist API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # `/team` is the cheapest authenticated probe — no pagination, single object.
    url = _build_url(LEMLIST_ENDPOINTS["team"].path, {})
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, auth=("", api_key), timeout=REQUEST_TIMEOUT_SECONDS
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LemlistResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LEMLIST_ENDPOINTS[endpoint]
    # One session reused across pages so urllib3 keeps the connection alive.
    session = make_tracked_session(redact_values=(api_key,))
    base_params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value)

    if not config.paginate:
        data = _fetch(session, _build_url(config.path, base_params), api_key, logger)
        # `/team` returns a single object; the other non-paginated endpoints return an array.
        if config.single_object:
            if isinstance(data, dict):
                yield [data]
        elif isinstance(data, list) and data:
            yield data
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0

    while True:
        params = {**base_params, "limit": PAGE_SIZE, "offset": offset}
        page = _fetch(session, _build_url(config.path, params), api_key, logger)

        # Paginated endpoints always return a JSON array; guard against an unexpected object.
        if not isinstance(page, list) or not page:
            break

        yield page

        # A short page means we've reached the end — lemlist has no explicit "next" signal.
        if len(page) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(LemlistResumeConfig(offset=offset))


def lemlist_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LemlistResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LEMLIST_ENDPOINTS[endpoint]

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
        sort_mode=config.sort_mode,
    )
