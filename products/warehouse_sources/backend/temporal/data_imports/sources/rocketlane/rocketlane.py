import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.settings import ROCKETLANE_ENDPOINTS

ROCKETLANE_BASE_URL = "https://api.rocketlane.com/api/1.0"
# The list endpoints cap `pageSize` at 100 (values above the cap fall back to 100), so 100 minimises
# round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an api-key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/users"


class RocketlaneRetryableError(Exception):
    pass


@dataclasses.dataclass
class RocketlaneResumeConfig:
    # Opaque cursor for the next page. Rocketlane returns a `nextPageToken` alongside `hasMore`; a
    # crashed full-refresh sync resumes from the last token it persisted. Note: Rocketlane tokens are
    # only valid for ~15 minutes, so a long-stalled resume may need to restart from the first page —
    # merge dedupes on the primary key either way.
    page_token: Optional[str] = None


def _headers(api_key: str) -> dict[str, str]:
    # Rocketlane expects the raw key in an `api-key` header — no "Bearer " prefix.
    return {"api-key": api_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((RocketlaneRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page_token: Optional[str],
    page_size: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    params: dict[str, Any] = {"pageSize": page_size}
    # Omit `pageToken` on the first request; an empty token returns page 1.
    if page_token:
        params["pageToken"] = page_token

    response = session.get(
        f"{ROCKETLANE_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    # Rocketlane signals rate limiting with 429 (error code TOO_MANY_REQUEST); back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise RocketlaneRetryableError(f"Rocketlane API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Rocketlane API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RocketlaneResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ROCKETLANE_ENDPOINTS[endpoint]
    # `redact_values` masks the api-key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_token: Optional[str] = resume.page_token if resume else None
    if resume and resume.page_token:
        logger.debug(f"Rocketlane: resuming {endpoint} from saved page token")

    while True:
        data = _fetch_page(session, config.path, page_token, PAGE_SIZE, logger)

        # `data` is always present in a well-formed list response; missing it means a malformed
        # response, so fail loudly rather than silently advancing past lost rows.
        rows = data["data"]
        if rows:
            yield rows

        pagination = data.get("pagination") or {}
        next_token = pagination.get("nextPageToken")
        # Stop when the API says there are no more pages, when it stops handing back a cursor, or when
        # a page comes back empty (guards against a server-side cursor bug looping forever).
        if not pagination.get("hasMore") or not next_token or not rows:
            break

        page_token = next_token
        # Save AFTER yielding so a crash re-fetches from the token pointing at the *next* page (the
        # already-yielded pages are persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(RocketlaneResumeConfig(page_token=page_token))


def rocketlane_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RocketlaneResumeConfig],
) -> SourceResponse:
    config = ROCKETLANE_ENDPOINTS[endpoint]

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
    """Probe a single list endpoint to validate the api-key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise. The api-key is account-wide, so one probe
    validates access to every list endpoint.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{ROCKETLANE_BASE_URL}{path}", params={"pageSize": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Rocketlane: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Rocketlane returned HTTP {response.status_code}"

    return 200, None
