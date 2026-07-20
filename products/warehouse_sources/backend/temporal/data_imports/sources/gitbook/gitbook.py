import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import GITBOOK_ENDPOINTS

GITBOOK_BASE_URL = "https://api.gitbook.com/v1"
# List endpoints accept a `limit` of up to 1000 per the OpenAPI spec; a moderate page keeps
# individual payloads small (change requests and comments embed document bodies).
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API token is genuine. The token inherits its owner's
# permissions, so per-endpoint access is validated lazily at sync time.
DEFAULT_PROBE_PATH = "/user"


class GitBookRetryableError(Exception):
    pass


@dataclasses.dataclass
class GitBookResumeConfig:
    # Fan-out parents (organization or space ids) whose pages have all been yielded already.
    completed_parent_ids: list[str] = dataclasses.field(default_factory=list)
    # Parent currently being paginated; `None` for the top-level organizations endpoint.
    current_parent_id: Optional[str] = None
    # Opaque `next.page` token for the next page within the current parent (or the top-level
    # list). A crashed full-refresh sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on the primary key.
    next_page: Optional[str] = None


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((GitBookRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    page: Optional[str],
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if page is not None:
        params["page"] = page

    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # GitBook enforces per-method rate limits surfaced via X-RateLimit-* headers and HTTP 429.
    if response.status_code == 429 or response.status_code >= 500:
        raise GitBookRetryableError(f"GitBook API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"GitBook API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Every list response is `{"items": [...], "next": {"page": "..."}}`; `next` is omitted on
    # the last page.
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise GitBookRetryableError(f"GitBook returned an unexpected payload for {url}: {type(data).__name__}")

    next_obj = data.get("next")
    next_page = next_obj.get("page") if isinstance(next_obj, dict) else None
    return data["items"], next_page


def _list_all_ids(session: requests.Session, path: str, logger: FilteringBoundLogger) -> list[str]:
    ids: list[str] = []
    page: Optional[str] = None
    while True:
        items, page = _fetch_page(session, f"{GITBOOK_BASE_URL}{path}", page, logger)
        ids.extend(item["id"] for item in items)
        if not page:
            return ids


def _parent_ids(session: requests.Session, parent: str, logger: FilteringBoundLogger) -> list[str]:
    org_ids = _list_all_ids(session, "/orgs", logger)
    if parent == "organization":
        return org_ids
    # Spaces are enumerated per organization: orgs -> spaces.
    space_ids: list[str] = []
    for org_id in org_ids:
        space_ids.extend(_list_all_ids(session, f"/orgs/{org_id}/spaces", logger))
    return space_ids


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GitBookResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = GITBOOK_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.parent is None:
        page = resume.next_page if resume else None
        if page:
            logger.debug(f"GitBook: resuming {endpoint} from page token {page}")
        while True:
            items, next_page = _fetch_page(session, f"{GITBOOK_BASE_URL}{config.path}", page, logger)
            if items:
                yield items
            if not next_page:
                return
            page = next_page
            # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages
            # are persisted); merge dedupes the re-pulled page on the primary key.
            resumable_source_manager.save_state(GitBookResumeConfig(next_page=next_page))

    else:
        completed = set(resume.completed_parent_ids) if resume else set()
        if completed:
            logger.debug(f"GitBook: resuming {endpoint}, skipping {len(completed)} completed parents")

        for parent_id in _parent_ids(session, config.parent, logger):
            if parent_id in completed:
                continue

            url = f"{GITBOOK_BASE_URL}{config.path.format(parent_id=parent_id)}"
            page = resume.next_page if (resume and resume.current_parent_id == parent_id) else None
            while True:
                items, next_page = _fetch_page(session, url, page, logger)
                if items:
                    if config.parent_id_key:
                        yield [{**item, config.parent_id_key: parent_id} for item in items]
                    else:
                        yield items
                if not next_page:
                    break
                page = next_page
                resumable_source_manager.save_state(
                    GitBookResumeConfig(
                        completed_parent_ids=sorted(completed),
                        current_parent_id=parent_id,
                        next_page=next_page,
                    )
                )

            completed.add(parent_id)
            resumable_source_manager.save_state(GitBookResumeConfig(completed_parent_ids=sorted(completed)))


def gitbook_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GitBookResumeConfig],
) -> SourceResponse:
    config = GITBOOK_ENDPOINTS[endpoint]

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
        response = session.get(f"{GITBOOK_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to GitBook: {e}"

    # GitBook answers 401 for an invalid token and 403 for a missing/unauthorized one.
    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"GitBook returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    status, message = check_access(api_token)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid GitBook API token"
    return False, message or "Could not validate GitBook API token"
