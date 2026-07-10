import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.settings import TEAMTAILOR_ENDPOINTS

TEAMTAILOR_BASE_URL = "https://api.teamtailor.com/v1"
# JSON:API caps `page[size]` at 30; the largest page minimises round trips.
PAGE_SIZE = 30
REQUEST_TIMEOUT_SECONDS = 60
# Every request must pin an API version; this dated value is a documented, stable release.
API_VERSION = "20240404"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/users"


class TeamtailorRetryableError(Exception):
    pass


@dataclasses.dataclass
class TeamtailorResumeConfig:
    # Absolute URL of the next page to fetch, taken verbatim from the JSON:API `links.next`.
    # `None` starts from the first page. Cursor pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_url: Optional[str] = None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_key}",
        "X-Api-Version": API_VERSION,
        "Accept": "application/vnd.api+json",
    }


@retry(
    retry=retry_if_exception_type((TeamtailorRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # `links.next` is a fully-formed URL that already carries the page cursor, so params are only
    # sent for the first request and omitted once we're following `next`.
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise TeamtailorRetryableError(f"Teamtailor API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Teamtailor API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # JSON:API responses are always an object with a top-level `data` array; a non-object payload
    # means a malformed response, so fail loudly rather than silently ending the sync.
    if not isinstance(data, dict):
        raise TeamtailorRetryableError(f"Teamtailor returned an unexpected payload for {url}: {type(data).__name__}")
    return data


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamtailorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = TEAMTAILOR_ENDPOINTS[endpoint]
    # `redact_values` masks the API key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_url = resume.next_url if resume else None
    if next_url:
        logger.debug(f"Teamtailor: resuming {endpoint} from saved cursor")

    while True:
        if next_url:
            data = _fetch_page(session, next_url, None, logger)
        else:
            data = _fetch_page(session, f"{TEAMTAILOR_BASE_URL}{config.path}", {"page[size]": PAGE_SIZE}, logger)

        items = data.get("data") or []
        if items:
            yield items

        # `links.next` is absent or null on the final page.
        next_url = (data.get("links") or {}).get("next")
        if not next_url:
            break

        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(TeamtailorResumeConfig(next_url=next_url))


def teamtailor_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamtailorResumeConfig],
) -> SourceResponse:
    config = TEAMTAILOR_ENDPOINTS[endpoint]

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
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{TEAMTAILOR_BASE_URL}{path}", params={"page[size]": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Teamtailor: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Teamtailor returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Teamtailor API key"
    return False, message or "Could not validate Teamtailor API key"
