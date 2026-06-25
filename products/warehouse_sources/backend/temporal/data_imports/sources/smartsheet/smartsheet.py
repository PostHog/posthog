import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import SMARTSHEET_ENDPOINTS

SMARTSHEET_BASE_URL = "https://api.smartsheet.com/2.0"
# Smartsheet list endpoints page with `page` (1-based) and `pageSize` (max 100).
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class SmartsheetRetryableError(Exception):
    pass


@dataclasses.dataclass
class SmartsheetResumeConfig:
    next_page: int


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_url(path: str, page: int) -> str:
    params = {"page": page, "pageSize": PAGE_SIZE}
    return f"{SMARTSHEET_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(access_token: str) -> bool:
    """Confirm the access token is valid. ``/users/me`` is a cheap authenticated probe
    that works for any valid token regardless of granted scopes."""
    try:
        response = make_tracked_session().get(
            f"{SMARTSHEET_BASE_URL}/users/me",
            headers=_get_headers(access_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartsheetResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SMARTSHEET_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.next_page if resume_config is not None else 1
    if resume_config is not None:
        logger.debug(f"Smartsheet: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((SmartsheetRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Smartsheet rate-limits at 300 req/min; 429s are retryable, as are transient 5xx.
        if response.status_code == 429 or response.status_code >= 500:
            raise SmartsheetRetryableError(
                f"Smartsheet API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Smartsheet API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(_build_url(config.path, page))

        items = data.get("data", []) or []
        if items:
            yield items

        total_pages = data.get("totalPages", 0) or 0
        if not items or page >= total_pages:
            break

        page += 1
        resumable_source_manager.save_state(SmartsheetResumeConfig(next_page=page))


def smartsheet_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartsheetResumeConfig],
) -> SourceResponse:
    config = SMARTSHEET_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
