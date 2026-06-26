import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import OMNISEND_ENDPOINTS

OMNISEND_BASE_URL = "https://api.omnisend.com/v3"

# Omnisend allows up to 250 items per page; larger pages mean fewer requests against the
# 400 req/min general rate limit.
PAGE_SIZE = 250

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class OmnisendRetryableError(Exception):
    pass


@dataclasses.dataclass
class OmnisendResumeConfig:
    # Fully-formed next-page URL from the API's `paging.next`; we follow it verbatim.
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-KEY": api_key,
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Cheap probe to confirm the API key is genuine. Returns (is_valid, status_code)."""
    try:
        session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
        response = session.get(f"{OMNISEND_BASE_URL}/contacts?{urlencode({'limit': 1})}", timeout=10)
        return response.status_code == 200, response.status_code
    except Exception:
        return False, None


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = OMNISEND_ENDPOINTS[endpoint]

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str | None = resume_config.next_url
        logger.debug(f"Omnisend: resuming {endpoint} from URL: {url}")
    else:
        url = f"{OMNISEND_BASE_URL}{config.path}?{urlencode({'limit': PAGE_SIZE})}"

    # One session reused across all pages (TCP/connection reuse). `tenacity` below is the sole
    # retry mechanism, so disable the transport's built-in urllib3 retries to avoid nested backoff.
    # `redact_values` masks the API key in logs and sample capture.
    session = make_tracked_session(headers=_get_headers(api_key), retry=Retry(total=0), redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((OmnisendRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise OmnisendRetryableError(
                f"Omnisend API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Omnisend API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    try:
        while url:
            data = fetch_page(url)
            # Fail loudly if the expected envelope key is missing (e.g. an API-shape change),
            # rather than silently reporting a successful sync of zero rows.
            items = data[config.data_key]
            next_url = data.get("paging", {}).get("next")

            if items:
                yield items

            # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the
            # primary key) rather than skipping it.
            if next_url:
                resumable_source_manager.save_state(OmnisendResumeConfig(next_url=next_url))

            url = next_url
    finally:
        session.close()


def omnisend_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
) -> SourceResponse:
    config = OMNISEND_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
