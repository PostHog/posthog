import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.settings import JUSTSIFT_ENDPOINTS

JUSTSIFT_BASE_URL = "https://api.justsift.com/v1"
# Sift caps pageSize at 100 (default 10); 100 minimises round trips over a typically modest
# people directory and field catalog.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm a data token is genuine and can read people. The token is
# org-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/search/people"


class JustSiftRetryableError(Exception):
    pass


@dataclasses.dataclass
class JustSiftResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on the
    # primary key.
    next_page: int = 1


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((JustSiftRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int,
    page_size: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{JUSTSIFT_BASE_URL}{path}",
        params={"page": page, "pageSize": page_size},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise JustSiftRetryableError(f"Sift API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Sift API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JustSiftResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = JUSTSIFT_ENDPOINTS[endpoint]
    # `redact_values` masks the bearer token in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"Sift: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, config.path, page, PAGE_SIZE, logger)

        # `data` is always present in the Sift envelope ({data, links, meta}); missing it means a
        # malformed response, so fail loudly rather than silently advancing past lost rows.
        items = data["data"]
        if items:
            yield items

        # Terminate on a short or empty page, or once the reported total has been covered. `/fields`
        # returns the whole catalog in one short page; `/search/people` paginates through the total.
        total = data.get("meta", {}).get("totalLength")
        if len(items) < PAGE_SIZE or (total is not None and page * PAGE_SIZE >= total):
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(JustSiftResumeConfig(next_page=page))


def justsift_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JustSiftResumeConfig],
) -> SourceResponse:
    config = JUSTSIFT_ENDPOINTS[endpoint]

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


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the data token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise. Sift returns clean HTTP status codes for an
    invalid or scope-limited token, so no body sniffing is needed.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{JUSTSIFT_BASE_URL}{path}", params={"page": 1, "pageSize": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Sift: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Sift returned HTTP {response.status_code}"

    return 200, None
