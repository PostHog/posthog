import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.settings import SIMPLECAST_ENDPOINTS

SIMPLECAST_BASE_URL = "https://api.simplecast.com"
# The list endpoints accept a `limit` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm a token is genuine. The token is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/podcasts"


class SimpleCastRetryableError(Exception):
    pass


@dataclasses.dataclass
class SimpleCastResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((SimpleCastRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    offset: int,
    limit: int,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch one page and report whether it is the last one.

    Returns ``(items, is_last_page)``. Simplecast wraps rows in a ``collection`` array and reports
    paging state under ``pages`` (``{"total": N, "current": N}``), so we can terminate either on a
    short/empty collection or once the current page reaches the total.
    """
    response = session.get(
        f"{SIMPLECAST_BASE_URL}{path}",
        params={"limit": limit, "offset": offset},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise SimpleCastRetryableError(f"Simplecast API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Simplecast API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Simplecast list endpoints return an object envelope: {"collection": [...], "pages": {...}}.
    if not isinstance(data, dict) or not isinstance(data.get("collection"), list):
        raise SimpleCastRetryableError(f"Simplecast returned an unexpected payload for {path}: {type(data).__name__}")

    items: list[dict[str, Any]] = data["collection"]

    pages = data.get("pages")
    is_last_page = False
    if isinstance(pages, dict):
        total = pages.get("total")
        current = pages.get("current")
        if isinstance(total, int) and isinstance(current, int):
            is_last_page = current >= total

    return items, is_last_page


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SimpleCastResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SIMPLECAST_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume and resume.offset > 0:
        logger.debug(f"Simplecast: resuming {endpoint} from offset {offset}")

    while True:
        items, is_last_page = _fetch_page(session, config.path, offset, PAGE_SIZE, logger)
        if items:
            yield items

        # A short/empty page or the paging metadata signalling the final page ends the collection.
        if is_last_page or len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SimpleCastResumeConfig(offset=offset))


def simplecast_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SimpleCastResumeConfig],
) -> SourceResponse:
    config = SIMPLECAST_ENDPOINTS[endpoint]

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
    """Probe a single endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{SIMPLECAST_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Simplecast: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Simplecast returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Simplecast API token"
    return False, message or "Could not validate Simplecast API token"
