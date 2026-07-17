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
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.settings import (
    SALESLOFT_ENDPOINTS,
    SALESLOFT_UPDATED_AT_FIELD,
    SalesloftEndpointConfig,
)

SALESLOFT_BASE_URL = "https://api.salesloft.com/v2"
# Salesloft caps per_page at 100; larger pages keep us under the per-page rate-limit
# cost penalties that escalate past page 100.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class SalesloftRetryableError(Exception):
    pass


@dataclasses.dataclass
class SalesloftResumeConfig:
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 string Salesloft expects."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _build_params(
    config: SalesloftEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if config.incremental:
        # Default sort key on these endpoints is `updated_at`; ascending order lets the
        # pipeline advance its incremental watermark deterministically.
        params["sort_direction"] = "ASC"

        if should_use_incremental_field and db_incremental_field_last_value is not None:
            filter_field = incremental_field or SALESLOFT_UPDATED_AT_FIELD
            params[f"{filter_field}[gte]"] = _format_datetime(db_incremental_field_last_value)

    return params


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    return f"{base_url}?{urlencode(params)}" if params else base_url


def validate_credentials(api_key: str) -> bool:
    try:
        response = make_tracked_session().get(f"{SALESLOFT_BASE_URL}/me", headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SalesloftResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SALESLOFT_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    base_url = f"{SALESLOFT_BASE_URL}{config.path}"

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        logger.debug(f"Salesloft: resuming {endpoint} from URL: {url}")
    else:
        params["page"] = 1
        url = _build_url(base_url, params)

    @retry(
        retry=retry_if_exception_type((SalesloftRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SalesloftRetryableError(
                f"Salesloft API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Salesloft API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = data.get("data", []) or []
        next_page = ((data.get("metadata") or {}).get("paging") or {}).get("next_page")

        if items:
            yield items

        if not next_page:
            break

        params["page"] = next_page
        next_url = _build_url(base_url, params)
        # Save AFTER yielding the current page so a crash re-fetches the next page rather
        # than skipping the page we just handed off (merge dedupes any re-yielded rows).
        resumable_source_manager.save_state(SalesloftResumeConfig(next_url=next_url))
        url = next_url


def salesloft_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SalesloftResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SALESLOFT_ENDPOINTS[endpoint]

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
        primary_keys=["id"],
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
