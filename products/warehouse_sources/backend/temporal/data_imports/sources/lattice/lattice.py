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
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.settings import LATTICE_ENDPOINTS

LATTICE_HOSTS = {
    "us": "https://api.latticehq.com",
    "emea": "https://api.emea.latticehq.com",
}
# Lattice's default page size is only 10; always request the max of 100.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# 240 req/min rate limit; 429s carry Retry-After but exponential backoff suffices.
MAX_RETRY_ATTEMPTS = 5


class LatticeRetryableError(Exception):
    pass


@dataclasses.dataclass
class LatticeResumeConfig:
    # Lattice cursor pagination: pass the previous page's endingCursor as
    # startingAfter; static params are rebuilt deterministically on resume.
    starting_after: str


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_key}"}, redact_values=(api_key,))


def _base_url(region: str) -> str:
    host = LATTICE_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid Lattice region: {region}")
    return host


def validate_credentials(region: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is valid with a cheap one-user probe.

    Keys inherit the creating user's privileges, so a key may lack access to a
    specific stream (403); only 401 means the key itself is bad."""
    try:
        base_url = _base_url(region)
    except ValueError as e:
        return False, str(e)

    try:
        response = _get_session(api_key).get(
            f"{base_url}/v1/users?{urlencode({'limit': 1})}",
            timeout=10,
        )
    except requests.RequestException as e:
        # Transport failures (timeouts, connection resets) are not auth failures;
        # surface the real error instead of mislabeling the key as invalid.
        return False, f"Could not reach Lattice: {e}"

    if response.status_code == 401:
        return False, "Invalid Lattice API key"
    return True, None


def get_rows(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LatticeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = LATTICE_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    base_url = _base_url(region)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    starting_after: Optional[str] = resume_config.starting_after if resume_config is not None else None
    if starting_after is not None:
        logger.debug(f"Lattice: resuming {endpoint} from cursor {starting_after}")

    @retry(
        retry=retry_if_exception_type((LatticeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise LatticeRetryableError(f"Lattice API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            # Omit the response body: Lattice error payloads can carry field-level
            # validation context or user-identifying data we don't want in logs.
            logger.error(f"Lattice API error: status={response.status_code}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if starting_after is not None:
            params["startingAfter"] = starting_after
        data = fetch_page(f"{base_url}{config.path}?{urlencode(params)}")
        items = data.get("data", []) or []

        if items:
            yield items

        ending_cursor = data.get("endingCursor")
        if not data.get("hasMore") or not ending_cursor or not items:
            break

        starting_after = ending_cursor
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(LatticeResumeConfig(starting_after=starting_after))


def lattice_source(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LatticeResumeConfig],
) -> SourceResponse:
    config = LATTICE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
