import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.settings import (
    OPENAQ_ENDPOINTS,
    OpenAQEndpointConfig,
)

OPENAQ_BASE_URL = "https://api.openaq.org"

# The v3 API caps page size at 1000 and rejects requests where page * limit exceeds 100_000
# (offset ceiling). We page in 1000s and stop each per-sensor fan-out at MAX_PAGES so we never
# cross that ceiling; ascending order + the incremental datetime filter means a truncated sensor
# resumes from its last synced value on the next sync rather than losing data.
OPENAQ_PAGE_SIZE: int = 1000
MAX_PAGES: int = 100

# The only sort field every v3 list endpoint accepts is `id`; sorting ascending gives page-stable
# pagination for the full-refresh reference tables.
_LIST_SORT_PARAMS = {"order_by": "id", "sort_order": "asc"}


class OpenAQRetryableError(Exception):
    pass


@dataclasses.dataclass
class OpenAQResumeConfig:
    # Next page to fetch (1-based). For list/sensors endpoints this pages the top-level resource;
    # for measurement fan-out it's the page within `parent_sensor_id`.
    page: int = 1
    # The sensor currently being fetched in a measurement fan-out. A stable sensor-id bookmark (not a
    # positional index) so sensors added/removed between a crash and the retry can't resume us into the
    # wrong sensor. None for list/sensors endpoints.
    parent_sensor_id: int | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def validate_credentials(api_key: str) -> bool:
    # /v3/parameters is a small reference list reachable by any valid key, so it's the cheapest
    # probe that the token itself is genuine.
    url = _build_url(f"{OPENAQ_BASE_URL}/v3/parameters", {"limit": 1})
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            OpenAQRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(6),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # Free-tier keys are limited to 60 req/min and 2000 req/hour; a 429 carries X-RateLimit-Reset
    # headers we could honor exactly, but exponential backoff keeps this simple and correct.
    if response.status_code == 429 or response.status_code >= 500:
        raise OpenAQRetryableError(f"OpenAQ API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"OpenAQ API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _format_time_value(value: Any, prefix: str) -> str:
    """Format an incremental cursor value for the OpenAQ measurement time filter.

    The raw/hourly endpoints take an ISO-8601 datetime (`datetime_from`); the daily/yearly
    aggregates take a calendar date (`date_from`).
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if prefix == "date":
            return aware.date().isoformat()
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat() if prefix == "date" else f"{value.isoformat()}T00:00:00Z"
    return str(value)


def _flatten_sensor(location: dict[str, Any], sensor: dict[str, Any]) -> dict[str, Any]:
    """Shape one embedded location sensor into a flat row with its parent-location context."""
    parameter = sensor.get("parameter") or {}
    return {
        # Direct access on the primary key so a malformed row fails fast rather than merging
        # every id-less sensor into one null-keyed row.
        "id": sensor["id"],
        "name": sensor.get("name"),
        "parameter_id": parameter.get("id"),
        "parameter_name": parameter.get("name"),
        "parameter_units": parameter.get("units"),
        "parameter_display_name": parameter.get("displayName"),
        "location_id": location.get("id"),
        "location_name": location.get("name"),
        "locality": location.get("locality"),
        "timezone": location.get("timezone"),
        "coordinates": location.get("coordinates"),
        "country": location.get("country"),
        "provider": location.get("provider"),
    }


def _flatten_measurement(item: dict[str, Any], sensor_id: int) -> dict[str, Any]:
    """Shape one measurement into a flat row keyed by (sensor_id, period start).

    A measurement carries no id of its own; its period start (`datetime_from`) plus the sensor it
    belongs to uniquely identify it, so both are lifted to the top level for the primary key.
    """
    period = item.get("period") or {}
    datetime_from = (period.get("datetimeFrom") or {}).get("utc")
    datetime_to = (period.get("datetimeTo") or {}).get("utc")
    parameter = item.get("parameter") or {}
    return {
        "sensor_id": sensor_id,
        "datetime_from": datetime_from,
        "datetime_to": datetime_to,
        "value": item.get("value"),
        "parameter_id": parameter.get("id"),
        "parameter_name": parameter.get("name"),
        "parameter_units": parameter.get("units"),
        "coordinates": item.get("coordinates"),
        "coverage": item.get("coverage"),
        "summary": item.get("summary"),
        "flag_info": item.get("flagInfo"),
    }


def _iter_location_pages(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger, start_page: int = 1
) -> Iterator[tuple[int, list[dict[str, Any]], bool]]:
    """Page through /v3/locations, yielding (page, locations, is_last_page)."""
    page = start_page
    while True:
        params = {**_LIST_SORT_PARAMS, "limit": OPENAQ_PAGE_SIZE, "page": page}
        data = _fetch_page(session, _build_url(f"{OPENAQ_BASE_URL}/v3/locations", params), headers, logger)
        results = data.get("results", [])
        is_last = len(results) < OPENAQ_PAGE_SIZE or page >= MAX_PAGES
        if page >= MAX_PAGES and len(results) == OPENAQ_PAGE_SIZE:
            logger.warning(f"OpenAQ: hit MAX_PAGES={MAX_PAGES} paging /v3/locations; stopping enumeration")
        yield page, results, is_last
        if is_last:
            break
        page += 1


def _iter_sensor_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[int]:
    """Walk /v3/locations once and yield each embedded sensor id (globally unique)."""
    for _page, locations, _is_last in _iter_location_pages(session, headers, logger):
        for location in locations:
            for sensor in location.get("sensors") or []:
                sensor_id = sensor.get("id")
                if sensor_id is not None:
                    yield sensor_id


def _get_list_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    config: OpenAQEndpointConfig,
    resumable_source_manager: ResumableSourceManager[OpenAQResumeConfig],
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume else 1

    while page <= MAX_PAGES:
        params = {**_LIST_SORT_PARAMS, "limit": OPENAQ_PAGE_SIZE, "page": page}
        data = _fetch_page(session, _build_url(f"{OPENAQ_BASE_URL}{config.path}", params), headers, logger)
        results = data.get("results", [])
        is_last = len(results) < OPENAQ_PAGE_SIZE

        for item in results:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                if not is_last:
                    resumable_source_manager.save_state(OpenAQResumeConfig(page=page + 1))

        if is_last:
            break
        page += 1


def _get_sensor_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[OpenAQResumeConfig],
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_page = resume.page if resume else 1

    for page, locations, is_last in _iter_location_pages(session, headers, logger, start_page):
        for location in locations:
            for sensor in location.get("sensors") or []:
                batcher.batch(_flatten_sensor(location, sensor))
                if batcher.should_yield():
                    yield batcher.get_table()
                    if not is_last:
                        resumable_source_manager.save_state(OpenAQResumeConfig(page=page + 1))


def _get_measurement_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    config: OpenAQEndpointConfig,
    resumable_source_manager: ResumableSourceManager[OpenAQResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    sensor_ids = list(_iter_sensor_ids(session, headers, logger))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = sensor_ids
    resume_page = 1
    if resume is not None and resume.parent_sensor_id is not None and resume.parent_sensor_id in sensor_ids:
        remaining = sensor_ids[sensor_ids.index(resume.parent_sensor_id) :]
        resume_page = resume.page
        logger.debug(f"OpenAQ: resuming {config.name} from sensor_id={resume.parent_sensor_id}, page={resume_page}")

    if config.time_param_prefix is None:
        raise ValueError(f"OpenAQ endpoint {config.name!r} has kind='measurement' but no time_param_prefix")
    time_params: dict[str, Any] = {}
    if should_use_incremental_field and db_incremental_field_last_value:
        time_params[f"{config.time_param_prefix}_from"] = _format_time_value(
            db_incremental_field_last_value, config.time_param_prefix
        )

    for index, sensor_id in enumerate(remaining):
        page = resume_page if index == 0 else 1
        resume_page = 1  # only the resumed-into sensor uses the saved page; the rest start fresh

        while page <= MAX_PAGES:
            params = {**time_params, "limit": OPENAQ_PAGE_SIZE, "page": page}
            path = config.path.format(sensors_id=sensor_id)
            data = _fetch_page(session, _build_url(f"{OPENAQ_BASE_URL}{path}", params), headers, logger)
            results = data.get("results", [])
            is_last = len(results) < OPENAQ_PAGE_SIZE or page >= MAX_PAGES
            if page >= MAX_PAGES and len(results) == OPENAQ_PAGE_SIZE:
                logger.warning(
                    f"OpenAQ: hit MAX_PAGES={MAX_PAGES} for {config.name} sensor_id={sensor_id}; "
                    "remaining rows sync on the next incremental run"
                )

            for item in results:
                batcher.batch(_flatten_measurement(item, sensor_id))
                if batcher.should_yield():
                    yield batcher.get_table()
                    if not is_last:
                        resumable_source_manager.save_state(
                            OpenAQResumeConfig(page=page + 1, parent_sensor_id=sensor_id)
                        )

            if is_last:
                break
            page += 1

        # Advance the bookmark to the next sensor so a crash between sensors resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(OpenAQResumeConfig(page=1, parent_sensor_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenAQResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = OPENAQ_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and every sensor, for fan-out) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. Redact the key so it never lands in
    # logged URLs or captured samples.
    session = make_tracked_session(redact_values=(api_key,))

    if config.kind == "list":
        yield from _get_list_rows(session, headers, logger, batcher, config, resumable_source_manager)
    elif config.kind == "sensors":
        yield from _get_sensor_rows(session, headers, logger, batcher, resumable_source_manager)
    else:
        yield from _get_measurement_rows(
            session,
            headers,
            logger,
            batcher,
            config,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def openaq_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenAQResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPENAQ_ENDPOINTS[endpoint]

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
        # Measurements come back oldest-first (ascending period start) per the v3 docs, which the
        # incremental watermark relies on. Unverified against the live API (no key available); noted
        # in the PR. If this proves wrong, the datetime_from server filter still bounds each fetch, so
        # completeness holds — only mid-sync watermark checkpointing would need sort_mode="desc".
        sort_mode="asc",
    )
