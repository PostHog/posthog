import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.settings import (
    TICKET_TAILOR_ENDPOINTS,
)

TICKET_TAILOR_BASE_URL = "https://api.tickettailor.com"
# List endpoints cap `limit` at 100; the largest page minimises round trips against the
# 5000 requests / 30 minutes rate limit.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. Keys are scoped to a whole box office,
# so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/v1/events"


class TicketTailorRetryableError(Exception):
    pass


@dataclasses.dataclass
class TicketTailorResumeConfig:
    # Cursor for the next page: Ticket Tailor paginates by passing the last item's object id as
    # `starting_after` (lists are returned newest-first). A crashed sync resumes from the page
    # after the last one yielded; merge dedupes on `id`. `None` means start from the first page.
    cursor: str | None = None


def _make_session(api_key: str) -> requests.Session:
    # Ticket Tailor authenticates via HTTP Basic with the API key as the username and no password.
    session = make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key,))
    session.auth = (api_key, "")
    return session


@retry(
    retry=retry_if_exception_type((TicketTailorRetryableError, requests.ReadTimeout, requests.ConnectionError)),
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
        params["starting_after"] = cursor

    response = session.get(
        f"{TICKET_TAILOR_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise TicketTailorRetryableError(
            f"Ticket Tailor API error (retryable): status={response.status_code}, path={path}"
        )

    if not response.ok:
        logger.error(f"Ticket Tailor API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    body = response.json()
    # List endpoints wrap records in {"data": [...], "links": {"next": ..., "previous": ...}},
    # where `links.next` is null on the last page.
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise TicketTailorRetryableError(
            f"Ticket Tailor returned an unexpected payload for {path}: {type(body).__name__}"
        )

    items: list[dict[str, Any]] = body["data"]
    links = body.get("links") or {}
    has_more = bool(links.get("next")) if isinstance(links, dict) else False
    return items, has_more


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TicketTailorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = TICKET_TAILOR_ENDPOINTS[endpoint]
    session = _make_session(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if resume and resume.cursor is not None:
        logger.debug(f"Ticket Tailor: resuming {endpoint} from cursor {cursor}")

    while True:
        items, has_more = _fetch_page(session, config.path, cursor, PAGE_SIZE, logger)
        if items:
            yield items

        if not has_more or not items:
            break

        # Cursor pagination advances by the last item's id — there is no numeric offset.
        cursor = items[-1]["id"]
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(TicketTailorResumeConfig(cursor=cursor))


def tickettailor_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TicketTailorResumeConfig],
) -> SourceResponse:
    config = TICKET_TAILOR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Not every object carries a stable creation timestamp (discounts, vouchers,
        # membership types), so we don't partition.
        partition_count=1,
        partition_size=1,
        # Lists are returned newest-first by object id. Inert while every endpoint is full
        # refresh, but declared so a future incremental cursor can't corrupt its watermark.
        sort_mode="desc",
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise. Ticket Tailor answers unauthenticated and
    invalid-key requests with 403.
    """
    session = _make_session(api_key)
    try:
        response = session.get(f"{TICKET_TAILOR_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Ticket Tailor: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Ticket Tailor returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Ticket Tailor API key"
    return False, message or "Could not validate Ticket Tailor API key"
