import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.settings import (
    PANDADOC_ENDPOINTS,
    PandaDocEndpointConfig,
)

PANDADOC_BASE_URL = "https://api.pandadoc.com/public/v1"
# PandaDoc list pages cap at 100 items.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Default rate limit is ~60 req/min (sandbox keys are far lower), so honor 429s
# with exponential backoff.
MAX_RETRY_ATTEMPTS = 5


class PandaDocRetryableError(Exception):
    pass


@dataclasses.dataclass
class PandaDocResumeConfig:
    # PandaDoc paginates with a 1-based page number; the static query params
    # (count, incremental filters, sort) are deterministically rebuilt from the
    # endpoint config and job inputs on resume.
    page: int


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"API-Key {api_key}"}, redact_values=(api_key,), retry=Retry(total=0)
    )


def _format_date_filter(value: Any) -> str:
    """Format an incremental cursor for PandaDoc's date filters (ISO 8601 UTC, e.g. 2024-01-02T03:04:05.000000Z)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(value)


def _build_params(
    config: PandaDocEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    page: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.paginated:
        params["count"] = PAGE_SIZE
        params["page"] = page

    if not config.incremental_params:
        return params

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_field = incremental_field or config.incremental_fields[0]["field"]
        filter_param = config.incremental_params.get(cursor_field)
        if filter_param is not None:
            params[filter_param] = _format_date_filter(db_incremental_field_last_value)
            # Ascending order on the cursor field so the incremental watermark
            # advances monotonically as pages are consumed.
            params["order_by"] = cursor_field
            return params

    # Full refresh: sort on the stable creation date so rows modified mid-sync
    # don't move across page boundaries.
    params["order_by"] = "date_created"
    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{PANDADOC_BASE_URL}{path}"
    return f"{PANDADOC_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a cheap one-document listing probe."""
    try:
        response = _get_session(api_key).get(
            _build_url("/documents", {"count": 1, "page": 1}),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PandaDocResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PANDADOC_ENDPOINTS[endpoint]
    session = _get_session(api_key)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.page if resume_config is not None else 1
    if resume_config is not None:
        logger.debug(f"PandaDoc: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((PandaDocRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise PandaDocRetryableError(
                f"PandaDoc API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"PandaDoc API error: status={response.status_code}, body={response.text}, url={page_url}")
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
        items = data.get(config.data_key, []) or []

        if items:
            yield items

        if not config.paginated or len(items) < PAGE_SIZE:
            break

        page += 1
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(PandaDocResumeConfig(page=page))


def pandadoc_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PandaDocResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PANDADOC_ENDPOINTS[endpoint]

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
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
