import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.settings import PERSISTIQ_ENDPOINTS

# The base URL already includes the `/v1` API version segment; endpoint paths are appended to it.
PERSISTIQ_BASE_URL = "https://api.persistiq.com/v1"
# The leads endpoint paginates at 100 records/page. per_page is not a documented parameter, so we
# only advance `page` and rely on the `has_more` flag to terminate.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint. `/users` is typically the smallest collection.
DEFAULT_PROBE_PATH = "/users"


class PersistiqRetryableError(Exception):
    pass


@dataclasses.dataclass
class PersistiqResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((PersistiqRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{PERSISTIQ_BASE_URL}{path}",
        params={"page": page},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise PersistiqRetryableError(f"PersistIQ API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"PersistIQ API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Every list endpoint returns an object envelope (`{"<resource>": [...], "has_more": ...}`);
    # a bare array or other type means a malformed response.
    if not isinstance(data, dict):
        raise PersistiqRetryableError(f"PersistIQ returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PersistiqResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PERSISTIQ_ENDPOINTS[endpoint]
    # `redact_values` masks the API key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"PersistIQ: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, config.path, page, logger)

        # The resource key is always present in a well-formed envelope; missing it means a malformed
        # response, so fail loudly rather than silently advancing the cursor past lost rows.
        items = data.get(config.list_key)
        if not isinstance(items, list):
            raise PersistiqRetryableError(f"PersistIQ response for {endpoint} is missing the '{config.list_key}' list")
        if items:
            yield items

        # `has_more` is the authoritative end-of-collection signal; an empty page is a defensive stop.
        if not data.get("has_more", False) or not items:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(PersistiqResumeConfig(next_page=page))


def persistiq_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PersistiqResumeConfig],
) -> SourceResponse:
    config = PERSISTIQ_ENDPOINTS[endpoint]

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
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{PERSISTIQ_BASE_URL}{path}", params={"page": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to PersistIQ: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"PersistIQ returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid PersistIQ API key"
    return False, message or "Could not validate PersistIQ API key"
