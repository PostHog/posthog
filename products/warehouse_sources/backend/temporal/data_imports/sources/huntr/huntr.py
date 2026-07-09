import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.settings import HUNTR_ENDPOINTS

HUNTR_BASE_URL = "https://api.huntr.co/org"
# The list endpoints accept a `limit`; the docs don't state a hard maximum, so 100 keeps each page
# reasonably sized while minimising round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an access token is genuine. The org access token is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/members"


class HuntrRetryableError(Exception):
    pass


@dataclasses.dataclass
class HuntrResumeConfig:
    # Cursor for the next page to fetch — Huntr returns the `id` of the last object on the page as
    # `next`, and passing it back fetches the following page. Cursor pagination is deterministic, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next: str | None = None


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((HuntrRetryableError, requests.ReadTimeout, requests.ConnectionError)),
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
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, Any] = {"limit": limit}
    # The first request omits `next`; subsequent requests pass the cursor from the previous page.
    if cursor is not None:
        params["next"] = cursor

    response = session.get(
        f"{HUNTR_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise HuntrRetryableError(f"Huntr API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Huntr API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Huntr list endpoints wrap results in {"data": [...], "next": "<cursor>"}.
    if not isinstance(data, dict):
        raise HuntrRetryableError(f"Huntr returned an unexpected payload for {path}: {type(data).__name__}")

    items = data.get("data")
    if not isinstance(items, list):
        raise HuntrRetryableError(f"Huntr returned an unexpected 'data' field for {path}: {type(items).__name__}")

    next_cursor = data.get("next")
    return items, next_cursor if isinstance(next_cursor, str) else None


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HuntrResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = HUNTR_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(access_token), redact_values=(access_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next if resume else None
    if resume and resume.next is not None:
        logger.debug(f"Huntr: resuming {endpoint} from cursor {cursor}")

    while True:
        items, next_cursor = _fetch_page(session, config.path, cursor, PAGE_SIZE, logger)
        if items:
            yield items

        # A missing/null `next` cursor marks the end of the collection. An empty page also terminates
        # defensively so a lingering cursor can never produce an infinite loop.
        if not next_cursor or not items:
            break

        cursor = next_cursor
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(HuntrResumeConfig(next=cursor))


def huntr_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HuntrResumeConfig],
) -> SourceResponse:
    config = HUNTR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(access_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the access token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(access_token), redact_values=(access_token,))
    try:
        response = session.get(f"{HUNTR_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Huntr: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Huntr returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    status, message = check_access(access_token)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Huntr access token"
    return False, message or "Could not validate Huntr access token"
