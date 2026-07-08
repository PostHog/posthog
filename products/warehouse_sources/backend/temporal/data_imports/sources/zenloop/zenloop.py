import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.settings import ZENLOOP_ENDPOINTS

ZENLOOP_BASE_URL = "https://api.zenloop.com/v1"
# Zenloop's list endpoints default to 50 rows per page; keep that size and paginate.
PER_PAGE = 50
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API token is genuine. The token inherits its user's account
# permissions, so one probe validates access to the list endpoints exposed here.
DEFAULT_PROBE_PATH = "/surveys"


class ZenloopRetryableError(Exception):
    pass


@dataclasses.dataclass
class ZenloopResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((ZenloopRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int,
    per_page: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{ZENLOOP_BASE_URL}{path}",
        params={"page": page, "per_page": per_page},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise ZenloopRetryableError(f"Zenloop API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Zenloop API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZenloopResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ZENLOOP_ENDPOINTS[endpoint]
    # `redact_values` masks the token in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"Zenloop: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, config.path, page, PER_PAGE, logger)

        # The row list is always present under its named key in the envelope; missing it means a
        # malformed response, so fail loudly rather than silently advancing past lost rows.
        items = data[config.response_key]
        if items:
            yield items

        # Zenloop exposes no reliable "has more" flag, so a short page marks the end: a page with
        # fewer than PER_PAGE rows cannot be followed by another full page.
        if len(items) < PER_PAGE:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(ZenloopResumeConfig(next_page=page))


def zenloop_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZenloopResumeConfig],
) -> SourceResponse:
    config = ZENLOOP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
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


def check_access(api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(f"{ZENLOOP_BASE_URL}{path}", params={"page": 1, "per_page": 5}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Zenloop: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Zenloop returned HTTP {response.status_code}"

    return 200, None
