import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.settings import RUDDR_ENDPOINTS

RUDDR_BASE_URL = "https://www.ruddr.io/api/workspace"
# List endpoints accept a `limit` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is workspace-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/clients"


class RuddrRetryableError(Exception):
    pass


@dataclasses.dataclass
class RuddrResumeConfig:
    # Cursor for the next page: Ruddr paginates by passing the last item's `id` as `startingAfter`.
    # A crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes on
    # `id`. `None` means start from the first page.
    cursor: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((RuddrRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    cursor: str | None,
    limit: int,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], bool]:
    params: dict[str, Any] = {"limit": limit}
    if cursor is not None:
        params["startingAfter"] = cursor

    response = session.get(
        f"{RUDDR_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise RuddrRetryableError(f"Ruddr API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Ruddr API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Ruddr list endpoints wrap records in {"results": [...], "hasMore": bool}.
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise RuddrRetryableError(f"Ruddr returned an unexpected payload for {path}: {type(data).__name__}")

    results: list[dict[str, Any]] = data["results"]
    has_more = bool(data.get("hasMore"))
    return results, has_more


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RuddrResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = RUDDR_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if resume and resume.cursor is not None:
        logger.debug(f"Ruddr: resuming {endpoint} from cursor {cursor}")

    while True:
        items, has_more = _fetch_page(session, config.path, cursor, PAGE_SIZE, logger)
        if items:
            yield items

        # `hasMore` is false (or the page came back empty) once we've reached the end of the list.
        if not has_more or not items:
            break

        # Cursor pagination advances by the last item's id — Ruddr has no numeric offset.
        cursor = items[-1]["id"]
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(RuddrResumeConfig(cursor=cursor))


def ruddr_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RuddrResumeConfig],
) -> SourceResponse:
    config = RUDDR_ENDPOINTS[endpoint]

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
        response = session.get(f"{RUDDR_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Ruddr: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Ruddr returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Ruddr API key"
    return False, message or "Could not validate Ruddr API key"
