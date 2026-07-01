import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.settings import (
    GONG_ENDPOINTS,
    GongEndpointConfig,
)

# Gong's API base URL. Workspace API keys (HTTP Basic) authenticate against this host regardless
# of the customer's data region, so it stays fixed (no user-supplied host -> no SSRF surface).
GONG_BASE_URL = "https://api.gong.io"

# `/v2/calls` requires `fromDateTime` and rejects ranges wider than 90 days per request.
MAX_WINDOW_DAYS = 90
# How far back the first sync of `calls` reaches when there is no incremental cursor yet.
# Bounded so an initial backfill doesn't exhaust Gong's aggressive daily rate limit.
DEFAULT_INITIAL_LOOKBACK_DAYS = 365


class GongRetryableError(Exception):
    pass


@dataclasses.dataclass
class GongResumeConfig:
    # ISO-8601 start of the next `calls` date window to fetch. Only the windowed `calls`
    # endpoint persists resume state; cursors are deliberately not cached (Gong expires
    # them quickly), so on resume we restart the in-progress window from scratch and let
    # primary-key merge semantics dedupe any re-yielded rows.
    window_start: Optional[str] = None


def _format_datetime(value: datetime) -> str:
    """ISO-8601 with a `Z` suffix, which Gong accepts for `fromDateTime`/`toDateTime`."""
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _to_datetime(value: Any) -> Optional[datetime]:
    """Coerce an incremental cursor value (datetime/date/ISO string) to an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    try:
        parsed = dateutil_parser.parse(str(value))
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _get_headers(access_key: str, access_key_secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{access_key}:{access_key_secret}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def validate_credentials(
    access_key: str, access_key_secret: str, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Probe a cheap endpoint to confirm the key pair is genuine.

    401 means the credentials are invalid. 403 means the credentials are valid but lack the
    scope for this particular resource - accepted at source-create (``schema_name is None``)
    because users may grant only the scopes they intend to sync.
    """
    url = f"{GONG_BASE_URL}/v2/workspaces"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(access_key, access_key_secret), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Gong access key or access key secret"
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Gong credentials do not have permission to access this endpoint"

    return False, f"Gong API returned an unexpected status code: {response.status_code}"


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{GONG_BASE_URL}{path}"
    return f"{GONG_BASE_URL}{path}?{urlencode(params)}"


def get_rows(
    access_key: str,
    access_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GongResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = GONG_ENDPOINTS[endpoint]
    headers = _get_headers(access_key, access_key_secret)

    @retry(
        retry=retry_if_exception_type((GongRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(url: str) -> dict[str, Any]:
        response = make_tracked_session().get(url, headers=headers, timeout=60)

        if response.status_code == 429 or response.status_code >= 500:
            raise GongRetryableError(f"Gong API error (retryable): status={response.status_code}, url={url}")

        # Gong's `/v2/calls` answers a date window with no processed calls using a 404
        # ("No calls found corresponding to the provided filters") rather than an empty 200.
        # Treat it as an empty page so the sync skips the window instead of failing.
        if config.uses_date_window and response.status_code == 404 and "no calls" in response.text.lower():
            return {}

        if not response.ok:
            logger.error(f"Gong API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    if config.uses_date_window:
        yield from _iter_windowed_rows(
            config,
            fetch_page,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _iter_cursor_rows(config, fetch_page)


def _iter_cursor_rows(config: GongEndpointConfig, fetch_page) -> Iterator[Any]:
    """Cursor-paginate a list endpoint until ``records.cursor`` is absent.

    Endpoints with no pagination (e.g. workspaces) return no cursor, so the loop exits after
    the first page.
    """
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"cursor": cursor} if cursor else {}
        data = fetch_page(_build_url(config.path, params))

        rows = data.get(config.response_key, [])
        if rows:
            yield rows

        cursor = data.get("records", {}).get("cursor")
        if not cursor:
            break


def _iter_windowed_rows(
    config: GongEndpointConfig,
    fetch_page,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GongResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    """Sync `/v2/calls` by iterating bounded date windows oldest-first, cursor-paginating each.

    State is saved after each completed window. Cursors are never persisted; on resume we
    restart the in-progress window from its start and let merge dedupe re-yielded rows.
    """
    end = datetime.now(UTC)

    last_value = _to_datetime(db_incremental_field_last_value) if should_use_incremental_field else None
    window_start = last_value or (end - timedelta(days=DEFAULT_INITIAL_LOOKBACK_DAYS))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.window_start:
        resumed = _to_datetime(resume_config.window_start)
        if resumed is not None:
            logger.debug(f"Gong: resuming calls from window start {resume_config.window_start}")
            window_start = resumed

    while window_start < end:
        window_end = min(window_start + timedelta(days=MAX_WINDOW_DAYS), end)
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {
                "fromDateTime": _format_datetime(window_start),
                "toDateTime": _format_datetime(window_end),
            }
            if cursor:
                params["cursor"] = cursor

            data = fetch_page(_build_url(config.path, params))

            rows = data.get(config.response_key, [])
            if rows:
                yield rows

            cursor = data.get("records", {}).get("cursor")
            if not cursor:
                break

        window_start = window_end
        resumable_source_manager.save_state(GongResumeConfig(window_start=_format_datetime(window_start)))


def gong_source(
    access_key: str,
    access_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GongResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GONG_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_key=access_key,
            access_key_secret=access_key_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # Windows are iterated oldest-first, so the cursor watermark advances correctly.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
