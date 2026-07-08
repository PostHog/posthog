import time
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
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import DEEL_ENDPOINTS

DEEL_BASE_URL = "https://api.letsdeel.com/rest/v2"
# Several Deel endpoints cap `limit` below 100, so stay safely under every cap.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
# Deel enforces a hard 5 req/s limit org-wide (shared across ALL tokens, 429
# with no rate-limit headers), so requests are proactively spaced out.
REQUEST_INTERVAL_SECONDS = 0.25
MAX_RETRY_ATTEMPTS = 5


class DeelRetryableError(Exception):
    pass


@dataclasses.dataclass
class DeelResumeConfig:
    # Offset-paginated endpoints persist the offset; the contracts keyset walk
    # persists Deel's opaque `after_cursor` instead.
    offset: Optional[int] = None
    cursor: Optional[str] = None


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the API token is valid with a cheap one-person listing probe.

    Scoped tokens may lack individual resource scopes (403); only 401 means the
    token itself is bad. A transient network failure surfaces as a distinct
    "could not reach Deel" error so it isn't mistaken for a bad token."""
    try:
        response = _get_session(api_token).get(
            f"{DEEL_BASE_URL}/people?{urlencode({'limit': 1})}",
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f"Could not reach Deel: {e}"

    if response.status_code == 401:
        return False, "Invalid Deel API token"
    return True, None


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = DEEL_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type((DeelRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def fetch(params: dict[str, Any]) -> dict[str, Any]:
        # Proactive spacing keeps us under the org-wide 5 req/s budget.
        time.sleep(REQUEST_INTERVAL_SECONDS)
        url = f"{DEEL_BASE_URL}{config.path}?{urlencode(params)}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise DeelRetryableError(f"Deel API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Deel API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "cursor":
        cursor: Optional[str] = resume_config.cursor if resume_config is not None else None
        if cursor is not None:
            logger.debug(f"Deel: resuming {endpoint} from cursor {cursor}")

        while True:
            params: dict[str, Any] = {"limit": PAGE_SIZE}
            if cursor is not None:
                params["after_cursor"] = cursor
            body = fetch(params)
            items = body.get("data", []) or []

            if items:
                yield items

            next_cursor = (body.get("page") or {}).get("cursor")
            if not next_cursor or not items:
                break

            cursor = next_cursor
            # Save state AFTER yielding the page so a crash re-yields the last
            # page (merge dedupes on primary key) rather than skipping it.
            resumable_source_manager.save_state(DeelResumeConfig(cursor=cursor))
        return

    offset = resume_config.offset if resume_config is not None and resume_config.offset is not None else 0
    if resume_config is not None:
        logger.debug(f"Deel: resuming {endpoint} from offset {offset}")

    while True:
        body = fetch({"limit": PAGE_SIZE, "offset": offset})
        items = body.get("data", []) or []

        if items:
            yield items

        if len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        resumable_source_manager.save_state(DeelResumeConfig(offset=offset))


def deel_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeelResumeConfig],
) -> SourceResponse:
    config = DEEL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
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
