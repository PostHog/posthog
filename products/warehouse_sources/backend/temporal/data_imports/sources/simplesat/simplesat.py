import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.settings import SIMPLESAT_ENDPOINTS

SIMPLESAT_BASE_URL = "https://api.simplesat.io/api/v1"
# The list endpoints return up to 100 records per page; the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/surveys"


class SimplesatRetryableError(Exception):
    pass


@dataclasses.dataclass
class SimplesatResumeConfig:
    # Absolute URL of the next page to fetch, taken verbatim from the response body's `next`
    # field. Cursor pagination is deterministic, so a crashed full-refresh sync resumes from the
    # page after the last one yielded; merge dedupes on `id`.
    next_url: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Simplesat-Token": api_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((SimplesatRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    method: str,
    url: str,
    list_key: str,
    params: Optional[dict[str, Any]],
    json_body: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    if method == "POST":
        response = session.post(url, params=params, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)
    else:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SimplesatRetryableError(f"Simplesat API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Simplesat API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Simplesat wraps the page in an object: {"<resource>": [...], "count": N, "next": ..., "previous": ...}.
    if not isinstance(data, dict):
        raise SimplesatRetryableError(f"Simplesat returned an unexpected payload for {url}: {type(data).__name__}")

    items = data.get(list_key, [])
    if not isinstance(items, list):
        raise SimplesatRetryableError(f"Simplesat returned a non-list `{list_key}` for {url}")

    next_url = data.get("next")
    if next_url is not None and not isinstance(next_url, str):
        raise SimplesatRetryableError(f"Simplesat returned a non-string `next` for {url}")

    return items, next_url


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SimplesatResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SIMPLESAT_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    # The search-style collection endpoints are POST; an empty body means "no date filter",
    # i.e. every record — the full refresh we want.
    json_body: Optional[dict[str, Any]] = {} if config.method == "POST" else None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume and resume.next_url:
        # Follow the saved cursor URL verbatim; it already carries the pagination params.
        url = resume.next_url
        params: Optional[dict[str, Any]] = None
        logger.debug(f"Simplesat: resuming {endpoint} from {url}")
    else:
        url = f"{SIMPLESAT_BASE_URL}{config.path}"
        params = {"page_size": PAGE_SIZE}

    while True:
        items, next_url = _fetch_page(session, config.method, url, config.list_key, params, json_body, logger)
        if items:
            yield items

        # A null `next` means we've reached the end of the collection.
        if not next_url:
            break

        # Follow the full `next` URL — it already carries page and page_size, so we don't re-send params.
        url = next_url
        params = None
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SimplesatResumeConfig(next_url=next_url))


def simplesat_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SimplesatResumeConfig],
) -> SourceResponse:
    config = SIMPLESAT_ENDPOINTS[endpoint]

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
        response = session.get(f"{SIMPLESAT_BASE_URL}{path}", params={"page_size": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Simplesat: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Simplesat returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Simplesat API key"
    return False, message or "Could not validate Simplesat API key"
