import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.settings import PLANHAT_ENDPOINTS

PLANHAT_BASE_URL = "https://api.planhat.com"
# Planhat list endpoints default to a `limit` of 100; the largest common page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API token is genuine. The token is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/companies"


class PlanhatRetryableError(Exception):
    pass


@dataclasses.dataclass
class PlanhatResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `_id`.
    offset: int = 0


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((PlanhatRetryableError, requests.ReadTimeout, requests.ConnectionError)),
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
) -> list[dict[str, Any]]:
    response = session.get(
        f"{PLANHAT_BASE_URL}{path}",
        params={"limit": limit, "offset": offset},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise PlanhatRetryableError(f"Planhat API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Planhat API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Planhat list endpoints return a bare JSON array of records.
    if not isinstance(data, list):
        raise PlanhatRetryableError(f"Planhat returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlanhatResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PLANHAT_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume and resume.offset > 0:
        logger.debug(f"Planhat: resuming {endpoint} from offset {offset}")

    while True:
        items = _fetch_page(session, config.path, offset, PAGE_SIZE, logger)
        if items:
            yield items

        # A short page (or an empty one) means we've reached the end of the collection.
        if len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(PlanhatResumeConfig(offset=offset))


def planhat_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlanhatResumeConfig],
) -> SourceResponse:
    config = PLANHAT_ENDPOINTS[endpoint]

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
    )


def check_access(api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        # Ask for a single row so the probe stays cheap regardless of account size.
        response = session.get(f"{PLANHAT_BASE_URL}{path}", params={"limit": 1, "offset": 0}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Planhat: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Planhat returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    status, message = check_access(api_token)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Planhat API token"
    return False, message or "Could not validate Planhat API token"
