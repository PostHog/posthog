import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.settings import (
    CHARTMOGUL_ENDPOINTS,
    ChartMogulEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CHARTMOGUL_BASE_URL = "https://api.chartmogul.com"
DEFAULT_PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class ChartMogulRetryableError(Exception):
    pass


@dataclasses.dataclass
class ChartMogulResumeConfig:
    # ChartMogul cursor pagination: each page returns an opaque `cursor` that
    # encodes the next page. We persist only the cursor — the static query
    # params (page size, incremental start-date) are deterministically rebuilt
    # from the config and the job inputs on resume.
    cursor: str


def _get_session(api_key: str) -> requests.Session:
    # ChartMogul uses HTTP Basic auth with the API key as the username and an
    # empty password. Redact the key from logged URLs / captured samples.
    return make_tracked_session(redact_values=(api_key,))


def _format_start_date(value: Any) -> str:
    """Format an incremental cursor value for ChartMogul's `start-date` filter (ISO 8601)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def validate_credentials(api_key: str) -> bool:
    url = f"{CHARTMOGUL_BASE_URL}/v1/data_sources"
    try:
        response = _get_session(api_key).get(url, auth=(api_key, ""), timeout=REQUEST_TIMEOUT_SECONDS)
        return response.status_code == 200
    except Exception:
        return False


def _build_initial_params(
    config: ChartMogulEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.paginated:
        params["per_page"] = DEFAULT_PAGE_SIZE

    if config.incremental_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_param] = _format_start_date(db_incremental_field_last_value)

    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChartMogulResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CHARTMOGUL_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    base_url = f"{CHARTMOGUL_BASE_URL}{config.path}"

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        params["cursor"] = resume_config.cursor
        logger.debug(f"ChartMogul: resuming {endpoint} from cursor: {resume_config.cursor}")

    @retry(
        retry=retry_if_exception_type((ChartMogulRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_params: dict[str, Any]) -> dict[str, Any]:
        url = f"{base_url}?{urlencode(page_params)}" if page_params else base_url
        response = session.get(url, auth=(api_key, ""), timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise ChartMogulRetryableError(
                f"ChartMogul API error (retryable): status={response.status_code}, url={base_url}"
            )

        if not response.ok:
            logger.error(f"ChartMogul API error: status={response.status_code}, body={response.text}, url={base_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(params)

        items = data.get(config.data_key, [])
        if items:
            yield items

        if not config.paginated:
            break

        has_more = data.get("has_more", False)
        cursor = data.get("cursor")
        if not has_more or not cursor:
            break

        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(ChartMogulResumeConfig(cursor=cursor))
        params["cursor"] = cursor


def chartmogul_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChartMogulResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CHARTMOGUL_ENDPOINTS[endpoint]

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
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # ChartMogul activities are returned in chronological (ascending) order
        # within the start-date window, so the incremental watermark advances
        # correctly. Non-incremental endpoints default to asc as well.
        sort_mode="asc",
    )
