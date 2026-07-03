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
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.settings import MOLLIE_ENDPOINTS

MOLLIE_BASE_URL = "https://api.mollie.com/v2"
# Mollie list pages cap at 250 items.
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60
# Mollie's rate limits are not publicly documented — honor 429s with backoff.
MAX_RETRY_ATTEMPTS = 5


class MollieRetryableError(Exception):
    pass


@dataclasses.dataclass
class MollieResumeConfig:
    # Mollie paginates via the HAL `_links.next.href` URL, which is
    # self-contained (ID-anchored `from` cursor), so the URL is all we persist.
    next_url: str


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_key}"}, redact_values=(api_key,))


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a cheap one-payment listing probe.

    Organization access tokens require a profileId on profile-scoped endpoints
    (a 4xx that isn't 401), so only 401 means the credential itself is bad."""
    try:
        response = _get_session(api_key).get(
            f"{MOLLIE_BASE_URL}/payments?{urlencode({'limit': 1})}",
            timeout=10,
        )
        return response.status_code != 401
    except requests.RequestException:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MollieResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = MOLLIE_ENDPOINTS[endpoint]
    session = _get_session(api_key)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Mollie: resuming {endpoint} from URL: {url}")
    else:
        url = f"{MOLLIE_BASE_URL}{config.path}?{urlencode({'limit': PAGE_SIZE})}"

    @retry(
        retry=retry_if_exception_type((MollieRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise MollieRetryableError(f"Mollie API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Mollie API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = (data.get("_embedded") or {}).get(config.embedded_key, []) or []

        if items:
            yield items

        next_url = ((data.get("_links") or {}).get("next") or {}).get("href")
        if not next_url:
            break

        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(MollieResumeConfig(next_url=next_url))
        url = next_url


def mollie_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MollieResumeConfig],
) -> SourceResponse:
    config = MOLLIE_ENDPOINTS[endpoint]

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
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )
