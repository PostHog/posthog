import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    CAL_COM_ENDPOINTS,
    CalComEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CAL_COM_BASE_URL = "https://api.cal.com/v2"
# Bookings `limit` and webhooks `take` are documented with a 250 maximum; the largest page
# minimizes round trips against the 120 req/min default rate limit.
PAGE_LIMIT = 250
REQUEST_TIMEOUT_SECONDS = 60
# Cheap single-object endpoint used to confirm an API key is genuine. The key is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/me"


class CalComRetryableError(Exception):
    pass


def _scrub_url(url: str | None) -> str:
    # Drop the query string before a URL reaches any error message or log line. Today the API key
    # rides in the Authorization header, but callers can append an arbitrary `path` (with a query)
    # in `check_access`, and future endpoints may take query-string credentials, so scrubbing keeps
    # those out of persisted job errors. The scheme/host/path stays intact so
    # `get_non_retryable_errors()` can still match on the base URL.
    if not url:
        return CAL_COM_BASE_URL
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


@dataclasses.dataclass
class CalComResumeConfig:
    # Opaque `pagination.nextCursor` for cursor-paginated endpoints (bookings). A crashed sync
    # resumes from the page after the last one yielded; merge dedupes the re-pulled page on `id`.
    cursor: str | None = None
    # `skip` offset for offset-paginated endpoints (webhooks).
    skip: int | None = None


def _headers(api_key: str, config: CalComEndpointConfig) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if config.api_version:
        headers["cal-api-version"] = config.api_version
    return headers


def _format_incremental_value(value: Any) -> str:
    # Cal.com's afterUpdatedAt/afterCreatedAt filters take ISO 8601 date strings; normalize to UTC
    # with a Z suffix to avoid timezone ambiguity.
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_incremental_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_incremental_params(
    config: CalComEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, str]:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return {}

    field = incremental_field or config.default_incremental_field
    if field is None:
        return {}

    param = config.incremental_param_by_field.get(field)
    if param is None:
        raise ValueError(f"Cal.com endpoint '{config.name}' has no server-side filter for field '{field}'")

    return {param: _format_incremental_value(db_incremental_field_last_value)}


@retry(
    retry=retry_if_exception_type((CalComRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params or None, timeout=REQUEST_TIMEOUT_SECONDS)

    # Default rate limit is 120 req/min; 429s and transient 5xx are retried with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise CalComRetryableError(
            f"Cal.com API error (retryable): status={response.status_code}, url={_scrub_url(response.url)}"
        )

    if not response.ok:
        logger.error(
            f"Cal.com API error: status={response.status_code}, body={response.text}, url={_scrub_url(response.url)}"
        )
        # Raise with the query scrubbed from the URL rather than calling raise_for_status(), whose
        # message embeds the full request URL. The base host stays intact so
        # `get_non_retryable_errors()` can still match on it.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {_scrub_url(response.url)}",
            response=response,
        )

    data = response.json()
    # Every v2 endpoint wraps its payload as {"status": "success", "data": ...}.
    if not isinstance(data, dict) or "data" not in data:
        raise CalComRetryableError(f"Cal.com returned an unexpected payload for {url}: {type(data).__name__}")

    return data


def _rows_from_body(body: dict[str, Any], config: CalComEndpointConfig, url: str) -> list[dict[str, Any]]:
    data = body["data"]
    if config.single_object:
        return [data] if isinstance(data, dict) else []
    if not isinstance(data, list):
        raise CalComRetryableError(f"Cal.com returned a non-list payload for {url}: {type(data).__name__}")
    return data


def _get_cursor_rows(
    session: requests.Session,
    config: CalComEndpointConfig,
    url: str,
    base_params: dict[str, Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor is not None:
        logger.debug(f"Cal.com: resuming {config.name} from cursor {cursor}")

    while True:
        params = {**base_params, "limit": PAGE_LIMIT}
        if cursor is not None:
            params["cursor"] = cursor

        body = _fetch_page(session, url, params, logger)
        items = _rows_from_body(body, config, url)
        if items:
            yield items

        pagination = body.get("pagination") or {}
        next_cursor = pagination.get("nextCursor")
        if not pagination.get("hasMore") or not next_cursor:
            break

        cursor = next_cursor
        # Save AFTER yielding so a crash re-fetches from the next cursor (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(CalComResumeConfig(cursor=next_cursor))


def _get_offset_rows(
    session: requests.Session,
    config: CalComEndpointConfig,
    url: str,
    base_params: dict[str, Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip = resume.skip if resume and resume.skip is not None else 0
    if skip:
        logger.debug(f"Cal.com: resuming {config.name} from offset {skip}")

    while True:
        params = {**base_params, "take": PAGE_LIMIT, "skip": skip}
        body = _fetch_page(session, url, params, logger)
        items = _rows_from_body(body, config, url)
        if items:
            yield items

        # These endpoints return no pagination metadata; a short (or empty) page means we're done.
        if len(items) < PAGE_LIMIT:
            break

        skip += PAGE_LIMIT
        resumable_source_manager.save_state(CalComResumeConfig(skip=skip))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CAL_COM_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key, config), redact_values=(api_key,))
    url = f"{CAL_COM_BASE_URL}{config.path}"
    base_params = _build_incremental_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    if config.pagination == "cursor":
        yield from _get_cursor_rows(session, config, url, base_params, logger, resumable_source_manager)
        return

    if config.pagination == "offset":
        yield from _get_offset_rows(session, config, url, base_params, logger, resumable_source_manager)
        return

    body = _fetch_page(session, url, base_params, logger)
    items = _rows_from_body(body, config, url)
    if items:
        yield items


def cal_com_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = CAL_COM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Bookings walk `Booking.uuid DESC` (newest-created first) when no status filter is passed,
        # and the opaque cursor doesn't honor sortUpdatedAt/sortCreated. "desc" makes the pipeline
        # commit the incremental watermark only after a complete sync, which stays correct
        # regardless of arrival order.
        sort_mode="desc" if config.incremental_fields else "asc",
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )
    try:
        response = session.get(f"{CAL_COM_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Cal.com: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Cal.com returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Cal.com API key"
    return False, message or "Could not validate Cal.com API key"
