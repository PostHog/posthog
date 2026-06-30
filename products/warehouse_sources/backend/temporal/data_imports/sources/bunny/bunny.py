import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import BUNNY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BUNNY_BASE_URL = "https://api.bunny.net"
# The list endpoints accept perPage 5..1000; 1000 minimises round trips for the typically small
# zone/library tables.
PER_PAGE = 1000
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an account API key is genuine. The AccessKey is account-wide, so
# one probe validates access to every Core API list endpoint.
DEFAULT_PROBE_PATH = "/pullzone"


class BunnyRetryableError(Exception):
    pass


@dataclasses.dataclass
class BunnyResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `Id`.
    next_page: int = 1


def _headers(access_key: str) -> dict[str, str]:
    return {"AccessKey": access_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((BunnyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
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
    # Always request page>=1 so the API returns the paginated envelope
    # ({Items, CurrentPage, TotalItems, HasMoreItems}); page=0 would return a bare array.
    response = session.get(
        f"{BUNNY_BASE_URL}{path}",
        params={"page": page, "perPage": per_page},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise BunnyRetryableError(f"bunny.net API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"bunny.net API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def get_rows(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BunnyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = BUNNY_ENDPOINTS[endpoint]
    # `redact_values` masks the account key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(access_key), redact_values=(access_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"bunny.net: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, config.path, page, PER_PAGE, logger)

        # `Items` is always present in the paginated envelope; missing it means a malformed
        # response, so fail loudly rather than silently advancing the cursor past lost rows.
        items = data["Items"]
        if items:
            yield items

        if not data.get("HasMoreItems", False):
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(BunnyResumeConfig(next_page=page))


def bunny_source(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BunnyResumeConfig],
) -> SourceResponse:
    config = BUNNY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_key=access_key,
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


def check_access(access_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the account API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise. bunny.net returns clean HTTP status codes
    (401 for ``Authorization has been denied``), so no body sniffing is needed.
    """
    session = make_tracked_session(headers=_headers(access_key), redact_values=(access_key,))
    try:
        response = session.get(f"{BUNNY_BASE_URL}{path}", params={"page": 1, "perPage": 5}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to bunny.net: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"bunny.net returned HTTP {response.status_code}"

    return 200, None
