import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.settings import TAVUS_ENDPOINTS

TAVUS_BASE_URL = "https://tavusapi.com/v2"
# Tavus list endpoints paginate with `page` (0-indexed) and `limit`; a large limit minimises round
# trips for the typically small video/replica/persona/conversation tables.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/replicas"


class TavusRetryableError(Exception):
    pass


@dataclasses.dataclass
class TavusResumeConfig:
    # Next page to fetch (0-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on the id.
    next_page: int = 0


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((TavusRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int,
    limit: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{TAVUS_BASE_URL}{path}",
        params={"page": page, "limit": limit},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise TavusRetryableError(f"Tavus API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Tavus API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TavusResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = TAVUS_ENDPOINTS[endpoint]
    # `redact_values` masks the API key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 0
    if resume and resume.next_page > 0:
        logger.debug(f"Tavus: resuming {endpoint} from page {page}")

    seen = 0
    while True:
        data = _fetch_page(session, config.path, page, PAGE_SIZE, logger)

        # `data` is always present in the list envelope ({data, total_count}); missing it means a
        # malformed response, so fail loudly rather than silently advancing past lost rows.
        rows = data["data"]
        if rows:
            yield rows
            seen += len(rows)

        total_count = data.get("total_count")

        # A short/empty page means the last page has been reached. Also stop once the running count
        # reaches the reported total, guarding against an off-by-one extra request.
        if len(rows) < PAGE_SIZE:
            break
        if total_count is not None and seen >= total_count:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(TavusResumeConfig(next_page=page))


def tavus_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TavusResumeConfig],
) -> SourceResponse:
    config = TAVUS_ENDPOINTS[endpoint]

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
    """Probe a single list endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{TAVUS_BASE_URL}{path}", params={"page": 0, "limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Tavus: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Tavus returned HTTP {response.status_code}"

    return 200, None
