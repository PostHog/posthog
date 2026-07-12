import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.settings import COASSEMBLE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Single shared host — Coassemble has no per-workspace subdomains.
COASSEMBLE_BASE_URL = "https://api.coassemble.com/api/v1/headless"
# The documented default page size for every list endpoint. We request it explicitly so the
# "short page means last page" termination check compares against the size the server enforces.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Hard cap on trackings pages per course (PAGE_SIZE * cap rows) so a paging bug on the vendor side
# can never produce an unbounded scan of a single course.
MAX_TRACKING_PAGES_PER_COURSE = 1_000
# Cheap list probe used to confirm credentials are genuine. The workspace API key is
# workspace-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/courses"


class CoassembleRetryableError(Exception):
    pass


@dataclasses.dataclass
class CoassembleResumeConfig:
    # Next page to fetch (0-indexed page-number pagination). Deterministic, so a crashed sync
    # resumes from the page after the last one yielded; merge dedupes the re-pulled page on the
    # primary key.
    next_page: int = 0
    # Trackings fan-out bookkeeping: courses fully paged through, and the course currently being
    # paged (whose next page is `next_page`). Course ids rather than an index so a shifted course
    # list between resume attempts can't skip a course.
    completed_course_ids: list[int] = dataclasses.field(default_factory=list)
    current_course_id: int | None = None


def _headers(workspace_id: str, api_key: str) -> dict[str, str]:
    # Vendor-specific scheme documented at https://developers.coassemble.com/get-started.
    return {
        "Authorization": f"COASSEMBLE:{workspace_id}:{api_key}",
        "Accept": "application/json",
    }


def _extract_items(data: Any, path: str) -> list[dict[str, Any]]:
    # List endpoints document a plain JSON array; accept common object wrappers defensively since
    # not every endpoint's response envelope is shown in the docs.
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    raise CoassembleRetryableError(f"Coassemble returned an unexpected payload for {path}: {type(data).__name__}")


@retry(
    retry=retry_if_exception_type((CoassembleRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int,
    logger: FilteringBoundLogger,
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"page": page, "length": PAGE_SIZE, **(extra_params or {})}

    response = session.get(f"{COASSEMBLE_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise CoassembleRetryableError(f"Coassemble API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Coassemble API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return _extract_items(response.json(), path)


def _iter_pages(
    session: requests.Session,
    path: str,
    logger: FilteringBoundLogger,
    start_page: int = 0,
    extra_params: dict[str, Any] | None = None,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Yield ``(page_number, items)`` from ``start_page`` until a short or empty page."""
    page = start_page
    while True:
        items = _fetch_page(session, path, page, logger, extra_params=extra_params)
        if items:
            yield page, items

        # A short page marks the end of the collection (we always request PAGE_SIZE).
        if len(items) < PAGE_SIZE:
            break

        page += 1


def _list_course_ids(session: requests.Session, logger: FilteringBoundLogger) -> list[int]:
    course_ids: list[int] = []
    for _, courses in _iter_pages(session, COASSEMBLE_ENDPOINTS["courses"].path, logger):
        course_ids.extend(course["id"] for course in courses)
    return course_ids


def get_rows(
    workspace_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoassembleResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = COASSEMBLE_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(workspace_id, api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_by_course:
        yield from _get_tracking_rows(session, logger, resumable_source_manager, resume)
        return

    page = resume.next_page if resume else 0
    if resume and resume.next_page > 0:
        logger.debug(f"Coassemble: resuming {endpoint} from page {page}")

    for fetched_page, items in _iter_pages(session, config.path, logger, start_page=page):
        yield items
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(CoassembleResumeConfig(next_page=fetched_page + 1))


def _get_tracking_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoassembleResumeConfig],
    resume: CoassembleResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    path = COASSEMBLE_ENDPOINTS["course_trackings"].path
    completed_course_ids = list(resume.completed_course_ids) if resume else []
    completed_set = set(completed_course_ids)

    for course_id in _list_course_ids(session, logger):
        if course_id in completed_set:
            continue

        start_page = resume.next_page if resume and resume.current_course_id == course_id else 0
        last_page_fetched: int | None = None

        for page, items in _iter_pages(session, path, logger, start_page=start_page, extra_params={"id": course_id}):
            for item in items:
                # Tracking rows don't reference their course, so inject it (also part of the
                # primary key — see settings.py).
                item["course_id"] = course_id
            yield items
            last_page_fetched = page
            resumable_source_manager.save_state(
                CoassembleResumeConfig(
                    next_page=page + 1,
                    completed_course_ids=completed_course_ids,
                    current_course_id=course_id,
                )
            )

            if page - start_page + 1 >= MAX_TRACKING_PAGES_PER_COURSE:
                logger.warning(
                    f"Coassemble: hit trackings page cap ({MAX_TRACKING_PAGES_PER_COURSE}) for course {course_id}; "
                    "remaining trackings for this course are skipped this sync"
                )
                break

        completed_course_ids.append(course_id)
        completed_set.add(course_id)
        resumable_source_manager.save_state(
            CoassembleResumeConfig(
                next_page=0,
                completed_course_ids=completed_course_ids,
                current_course_id=None,
            )
        )
        if last_page_fetched is not None:
            logger.debug(f"Coassemble: finished trackings for course {course_id}")


def coassemble_source(
    workspace_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoassembleResumeConfig],
) -> SourceResponse:
    config = COASSEMBLE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            workspace_id=workspace_id,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(workspace_id: str, api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the workspace credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(workspace_id, api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{COASSEMBLE_BASE_URL}{path}", params={"page": 0, "length": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Coassemble: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Coassemble returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(workspace_id: str, api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(workspace_id, api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Coassemble workspace ID or API key"
    return False, message or "Could not validate Coassemble credentials"
