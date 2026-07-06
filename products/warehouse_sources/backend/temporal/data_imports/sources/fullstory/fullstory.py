import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

FULLSTORY_BASE_URL = "https://api.fullstory.com"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Session/event data only exists behind Fullstory's async Data Export jobs;
# the v2 users listing is the one directly listable surface.
ENDPOINTS = ("users",)


class FullStoryRetryableError(Exception):
    pass


@dataclasses.dataclass
class FullStoryResumeConfig:
    # v2 listings paginate with an opaque next_page_token.
    next_page_token: str


def _get_session(api_key: str) -> requests.Session:
    # Fullstory's scheme is the raw API key after "Basic" (not base64 creds).
    return make_tracked_session(headers={"Authorization": f"Basic {api_key}"}, redact_values=(api_key,))


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a cheap one-user listing probe."""
    try:
        response = _get_session(api_key).get(
            f"{FULLSTORY_BASE_URL}/v2/users",
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(api_key)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_token: Optional[str] = resume_config.next_page_token if resume_config is not None else None
    if page_token is not None:
        logger.debug(f"Fullstory: resuming {endpoint} from page token")

    @retry(
        retry=retry_if_exception_type((FullStoryRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(token: Optional[str]) -> dict[str, Any]:
        url = f"{FULLSTORY_BASE_URL}/v2/{endpoint}"
        if token:
            url = f"{url}?{urlencode({'page_token': token})}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise FullStoryRetryableError(f"Fullstory API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Fullstory API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(page_token)
        items = data.get("results", []) or []

        if items:
            yield items

        next_token = data.get("next_page_token")
        if not next_token or not items:
            break

        page_token = next_token
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(FullStoryResumeConfig(next_page_token=page_token))


def fullstory_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
