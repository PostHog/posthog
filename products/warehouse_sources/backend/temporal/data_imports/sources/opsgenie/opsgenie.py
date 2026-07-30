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
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.settings import (
    OPSGENIE_ENDPOINTS,
    OpsgenieEndpointConfig,
)

OPSGENIE_BASE_URLS = {
    "us": "https://api.opsgenie.com",
    "eu": "https://api.eu.opsgenie.com",
}

# Opsgenie's max page size is 100; the default is 20.
PAGE_SIZE = 100

# The alert/incident search endpoints reject requests where `offset + limit` exceeds
# 20,000. Instead of truncating there, we re-slice the search into a new createdAt
# window starting from the last row we read (rows are sorted createdAt ascending, and
# createdAt is immutable, so the slices tile the full history).
MAX_SEARCH_RESULTS = 20_000

# Retry/throttle settings kept near the top for easy tuning. Opsgenie rate limits are
# token-bucket per API domain and return 429s; exponential backoff is the documented
# recovery.
RETRY_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 60


class OpsgenieRetryableError(Exception):
    pass


@dataclasses.dataclass
class OpsgenieResumeConfig:
    offset: int
    window_start_ms: Optional[int] = None


def _get_base_url(region: str) -> str:
    return OPSGENIE_BASE_URLS.get(region, OPSGENIE_BASE_URLS["us"])


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"GenieKey {api_key}",
        "Content-Type": "application/json",
    }


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Convert an incremental field value to epoch milliseconds for Opsgenie's search syntax."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return int(utc_value.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return _to_epoch_ms(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _parse_created_at_ms(item: dict[str, Any]) -> Optional[int]:
    created_at = item.get("createdAt")
    if not isinstance(created_at, str):
        return None
    try:
        return _to_epoch_ms(datetime.fromisoformat(created_at.replace("Z", "+00:00")))
    except ValueError:
        return None


def _build_params(
    config: OpsgenieEndpointConfig,
    offset: int,
    window_start_ms: Optional[int],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}

    if config.supports_search_window:
        # createdAt is immutable, so an ascending sort means new rows append to the end
        # and never shift pages we've already read. We send this on every sync (not just
        # incremental ones) so full refreshes paginate over a stable ordering too.
        params["sort"] = "createdAt"
        params["order"] = "asc"

        # A window opened mid-sync (after hitting the 20,000-result search cap) always
        # starts at or after the incremental cursor, so it takes precedence.
        start_ms = window_start_ms
        if start_ms is None and should_use_incremental_field and db_incremental_field_last_value is not None:
            start_ms = _to_epoch_ms(db_incremental_field_last_value)

        if start_ms is not None:
            # `>=` re-fetches rows sharing the boundary millisecond; merge dedupes on id.
            params["query"] = f"createdAt >= {start_ms}"

    return params


def validate_credentials(api_key: str, region: str, endpoint: Optional[str] = None) -> tuple[bool, int, str | None]:
    """Probe Opsgenie with a cheap single-row request.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is 0 on transport failure.
    The caller decides how to treat 403 (valid key, missing access for the probed endpoint).
    """
    config = OPSGENIE_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/v2/users"
    params = {"limit": 1} if config is None or config.paginated else {}
    url = f"{_get_base_url(region)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)

    if response.status_code == 200:
        return True, 200, None
    if response.status_code == 401:
        return False, 401, "Invalid Opsgenie API key"
    if response.status_code == 403:
        return False, 403, "Your Opsgenie API key does not have access to this resource"
    if response.status_code == 422:
        # Opsgenie rejects malformed keys with a 422 before checking auth.
        return False, 422, "Your Opsgenie API key format is not valid"

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, response.status_code, message


def get_rows(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpsgenieResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = OPSGENIE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    base_url = _get_base_url(region)

    @retry(
        retry=retry_if_exception_type((OpsgenieRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> dict:
        url = f"{base_url}{config.path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        response = make_tracked_session().get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise OpsgenieRetryableError(f"Opsgenie API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Opsgenie API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    if not config.paginated:
        data = fetch_page({})
        items = data.get("data", [])
        if items:
            yield items
        return

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config is not None else 0
    window_start_ms = resume_config.window_start_ms if resume_config is not None else None
    if resume_config is not None:
        logger.debug(f"Opsgenie: resuming {endpoint} from offset {offset}, window_start_ms {window_start_ms}")

    while True:
        params = _build_params(
            config, offset, window_start_ms, should_use_incremental_field, db_incremental_field_last_value
        )
        data = fetch_page(params)

        items = data.get("data", [])
        if not items:
            break

        yield items

        has_next = bool(data.get("paging", {}).get("next"))
        if not has_next or len(items) < PAGE_SIZE:
            break

        next_offset = offset + PAGE_SIZE
        if config.supports_search_window and next_offset + PAGE_SIZE > MAX_SEARCH_RESULTS:
            # Approaching the 20,000-result search cap: open a new createdAt window from
            # the last row read and restart the offset instead of truncating the sync.
            new_window_start_ms = _parse_created_at_ms(items[-1])
            if new_window_start_ms is None or new_window_start_ms == window_start_ms:
                # Can't advance the window (missing createdAt, or >20k rows share one
                # millisecond) — stop rather than loop on the same slice forever.
                logger.warning(
                    f"Opsgenie: unable to advance search window for endpoint '{endpoint}' at offset "
                    f"{next_offset}; stopping pagination (results may be truncated)"
                )
                break
            window_start_ms = new_window_start_ms
            offset = 0
        else:
            offset = next_offset

        # Save AFTER yielding so a crash re-fetches the last page; merge dedupes on primary key.
        resumable_source_manager.save_state(OpsgenieResumeConfig(offset=offset, window_start_ms=window_start_ms))


def opsgenie_source(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpsgenieResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPSGENIE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # Search-window endpoints request createdAt ascending; full-refresh endpoints
        # replace wholesale, so ascending is correct everywhere.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
