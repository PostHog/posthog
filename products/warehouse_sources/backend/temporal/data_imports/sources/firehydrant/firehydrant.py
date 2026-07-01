import time
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
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import FIREHYDRANT_ENDPOINTS

FIREHYDRANT_BASE_URL = "https://api.firehydrant.io"
# FireHydrant caps per_page at 200. 100 keeps each response comfortably small while halving the
# request count versus the default page size.
PAGE_SIZE = 100
# Cap how long we'll honor a Retry-After before falling back to tenacity's own backoff.
MAX_RETRY_AFTER_SECONDS = 60


class FireHydrantRetryableError(Exception):
    """Raised for transient FireHydrant API failures (429 / 5xx) that should be retried."""


@dataclasses.dataclass
class FireHydrantResumeConfig:
    # The next 1-indexed page to fetch. FireHydrant paginates with `page` / `per_page` query params and
    # returns a `pagination.next` page number (or null) in each response body.
    next_page: int


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, page: int) -> str:
    query = urlencode({"page": page, "per_page": PAGE_SIZE})
    return f"{FIREHYDRANT_BASE_URL}{path}?{query}"


def _fetch_page_once(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429:
        # FireHydrant returns a Retry-After header when the 50-req/10s account limit is exceeded.
        # Honor it (bounded), then raise so tenacity retries.
        retry_after = response.headers.get("Retry-After")
        delay = min(int(retry_after), MAX_RETRY_AFTER_SECONDS) if retry_after and retry_after.isdigit() else 1
        logger.warning(f"FireHydrant rate limited (429): sleeping {delay}s before retry, url={url}")
        time.sleep(delay)
        raise FireHydrantRetryableError(f"FireHydrant rate limited: url={url}")

    if response.status_code >= 500:
        raise FireHydrantRetryableError(f"FireHydrant API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"FireHydrant API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


# Retry transport failures and retryable statuses (429 / 5xx) with bounded exponential backoff. The
# core request logic lives in `_fetch_page_once` so it can be unit-tested without tenacity's waits.
_fetch_page = retry(
    retry=retry_if_exception_type((FireHydrantRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)(_fetch_page_once)


def validate_credentials(api_key: str, schema_name: str | None = None) -> tuple[bool, str | None]:
    """Probe the authenticated ping endpoint to confirm the token is genuine.

    FireHydrant API keys default to Owner-level permissions, so a valid token can reach every
    resource. A 403 therefore almost never happens, but if it does at source-create time we accept it
    (the token is real; sync-time permission errors are handled by `get_non_retryable_errors`).
    """
    url = f"{FIREHYDRANT_BASE_URL}/v1/ping"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, "Could not reach the FireHydrant API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 403 and schema_name is None:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid FireHydrant API key"
    return False, f"FireHydrant API returned an unexpected status: {response.status_code}"


def _extract_items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Pull the row list out of a FireHydrant response.

    Paginated endpoints wrap rows in a top-level `data` array; a few endpoints return a bare list or an
    object with no `data` key, so we degrade gracefully rather than assume a single shape.
    """
    if isinstance(payload, list):
        return payload
    data = payload.get("data")
    if isinstance(data, list):
        return data
    return []


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FireHydrantResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FIREHYDRANT_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1

    while True:
        payload = _fetch_page(session, _build_url(config.path, page), headers, logger)
        items = _extract_items(payload)
        if items:
            yield items

        pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
        next_page = pagination.get("next")
        if not next_page:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(FireHydrantResumeConfig(next_page=next_page))
        page = next_page


def firehydrant_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FireHydrantResumeConfig],
) -> SourceResponse:
    config = FIREHYDRANT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
