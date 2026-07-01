import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    SHIPSTATION_ENDPOINTS,
    ShipStationEndpointConfig,
)

SHIPSTATION_BASE_URL = "https://ssapi.shipstation.com"
# ShipStation list pages cap at 500 items.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
# Hard limit of 40 requests/minute per key pair; 429s carry rate-limit headers
# but exponential backoff up to a minute is sufficient.
MAX_RETRY_ATTEMPTS = 5

# All ShipStation v1 DateTime values are US Pacific time, not UTC.
SHIPSTATION_TZ = ZoneInfo("America/Los_Angeles")


class ShipStationRetryableError(Exception):
    pass


@dataclasses.dataclass
class ShipStationResumeConfig:
    # ShipStation paginates with a 1-based page number; the static query params
    # are deterministically rebuilt from the endpoint config and job inputs.
    page: int


def _get_session(api_key: str, api_secret: str) -> requests.Session:
    session = make_tracked_session(redact_values=(api_key, api_secret))
    session.auth = (api_key, api_secret)
    return session


def _format_date_filter(value: Any) -> str:
    """Format an incremental cursor for ShipStation's date filters.

    The API both stores and filters in US Pacific time ('yyyy-mm-dd hh:mm:ss').
    Naive values are assumed to already be Pacific (they come from API rows);
    aware values are converted."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is None else value.astimezone(SHIPSTATION_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    # Row values look like '2024-01-02T03:04:05.0000000'; the filter accepts the
    # space-separated form, so normalize the separator and drop fractions.
    text = str(value).replace("T", " ")
    return text.split(".")[0]


def _build_params(
    config: ShipStationEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    page: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.paginated:
        params["pageSize"] = PAGE_SIZE
        params["page"] = page

    if not config.incremental_params:
        return params

    cursor_field = incremental_field or config.incremental_fields[0]["field"]

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        filter_param = config.incremental_params.get(cursor_field)
        if filter_param is not None:
            params[filter_param] = _format_date_filter(db_incremental_field_last_value)

    # Ascending sort on the cursor field (when the endpoint documents one) keeps
    # page boundaries stable and advances the incremental watermark monotonically.
    sort_by = config.sort_by.get(cursor_field)
    if sort_by is not None:
        params["sortBy"] = sort_by
        params["sortDir"] = "ASC"

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{SHIPSTATION_BASE_URL}{path}"
    return f"{SHIPSTATION_BASE_URL}{path}?{urlencode(params)}"


def _extract_items(data: Any, data_key: Optional[str]) -> list[dict[str, Any]]:
    if data_key is None:
        return data if isinstance(data, list) else []
    if not isinstance(data, dict):
        return []
    items = data.get(data_key)
    return items if isinstance(items, list) else []


def validate_credentials(api_key: str, api_secret: str) -> bool:
    """Confirm the key pair is valid with a cheap one-store listing probe."""
    try:
        response = _get_session(api_key, api_secret).get(
            f"{SHIPSTATION_BASE_URL}/stores",
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShipStationResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SHIPSTATION_ENDPOINTS[endpoint]
    session = _get_session(api_key, api_secret)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.page if resume_config is not None else 1
    if resume_config is not None:
        logger.debug(f"ShipStation: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((ShipStationRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=70),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise ShipStationRetryableError(
                f"ShipStation API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"ShipStation API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        url = _build_url(
            config.path,
            _build_params(
                config, should_use_incremental_field, db_incremental_field_last_value, incremental_field, page
            ),
        )
        data = fetch_page(url)
        items = _extract_items(data, config.data_key)

        if items:
            yield items

        if not config.paginated:
            break

        total_pages = data.get("pages") if isinstance(data, dict) else None
        if total_pages is not None:
            if page >= total_pages:
                break
        elif len(items) < PAGE_SIZE:
            break

        page += 1
        # Save state after processing the page (whether or not it had items) so a
        # resume starts at the next page. Advancing past empty intermediate pages
        # avoids redundant API calls on resume; for non-empty pages, a crash before
        # save_state re-yields the page, which is safe because merge dedupes on
        # primary key.
        resumable_source_manager.save_state(ShipStationResumeConfig(page=page))


def shipstation_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShipStationResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SHIPSTATION_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            api_secret=api_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
