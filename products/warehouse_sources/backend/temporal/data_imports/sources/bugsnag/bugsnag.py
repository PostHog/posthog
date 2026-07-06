import re
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.settings import (
    BUGSNAG_ENDPOINTS,
    BugsnagEndpointConfig,
    BugsnagScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# BugSnag uses a single global host for its Data Access API. On-prem / Enterprise installs use a
# custom host, which this source does not yet support.
BUGSNAG_BASE_URL = "https://api.bugsnag.com"
# BugSnag's documented per_page maximum for list endpoints.
PAGE_SIZE = 100
# The Data Access API is versioned via the X-Version header. v2 is current; v1 is decommissioned.
BUGSNAG_API_VERSION = "2"


class BugsnagRetryableError(Exception):
    pass


@dataclasses.dataclass
class BugsnagResumeConfig:
    # Next page URL (from the Link header) to fetch. None means "start the current parent at its
    # first page" — used when the bookmark advances to a new fan-out parent whose first page URL
    # isn't known until it's built.
    next_url: str | None = None
    # The fan-out parent currently being processed, identified by its stable id (organization_id
    # for per-org endpoints, project_id for per-project ones). A stable id rather than a positional
    # index so parents added/removed between a crash and the retry can't resume into the wrong one.
    # None for the top-level (non-fan-out) organizations endpoint.
    parent_id: str | None = None


@dataclasses.dataclass
class _FanOutParent:
    # Id used to resolve the endpoint path and to bookmark resume position.
    resume_id: str
    # kwargs passed to ``str.format`` on the endpoint path template.
    path_kwargs: dict[str, str]
    # Parent identifiers injected into every child row so the composite primary key is unique
    # table-wide and the rows are joinable back to their organization/project.
    inject: dict[str, str]


def _get_headers(auth_token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {auth_token}",
        "X-Version": BUGSNAG_API_VERSION,
        "Content-Type": "application/json",
    }


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with rel="next" from BugSnag's Link header, if any.

    BugSnag paginates via the Link response header (the same RFC 5988 format GitHub uses)
    rather than page parameters in the body, so we follow the `next` relation until it's gone.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


@retry(
    retry=retry_if_exception_type((BugsnagRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger):
    response = session.get(page_url, headers=headers, timeout=60)

    # BugSnag rate limits per 1-minute window and returns 429 on exceed; retry those plus
    # transient 5xx. Exponential backoff covers the (typically sub-minute) reset window.
    if response.status_code == 429 or response.status_code >= 500:
        raise BugsnagRetryableError(f"BugSnag API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        logger.error(f"BugSnag API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response


def _fetch_list_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one page of a BugSnag list endpoint, returning (items, next_page_url).

    BugSnag list endpoints return a top-level JSON array; the next-page cursor lives in the
    Link header, not the body."""
    response = _fetch_page(session, url, headers, logger)
    data = response.json()
    if not isinstance(data, list):
        # Defensive: a non-list body has no rows to emit and no Link cursor to follow.
        return [], None
    return data, _parse_next_url(response.headers.get("Link", ""))


def _iter_all_pages(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[dict[str, Any]]:
    """Yield every item across all pages of a list endpoint, following the Link header."""
    while True:
        items, next_url = _fetch_list_page(session, url, headers, logger)
        yield from items
        if not next_url:
            return
        url = next_url


def _resolve_org_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    url = _build_url(f"{BUGSNAG_BASE_URL}/user/organizations", {"per_page": PAGE_SIZE})
    return [org["id"] for org in _iter_all_pages(session, url, headers, logger)]


def _resolve_parents(
    session: requests.Session, headers: dict[str, str], config: BugsnagEndpointConfig, logger: FilteringBoundLogger
) -> list[_FanOutParent]:
    """Build the ordered list of fan-out parents for a per-org or per-project endpoint."""
    org_ids = _resolve_org_ids(session, headers, logger)

    if config.scope == BugsnagScope.PER_ORG:
        return [
            _FanOutParent(
                resume_id=org_id,
                path_kwargs={"organization_id": org_id},
                inject={"organization_id": org_id},
            )
            for org_id in org_ids
        ]

    # PER_PROJECT: walk each organization's projects and flatten to (org_id, project_id) pairs.
    parents: list[_FanOutParent] = []
    for org_id in org_ids:
        projects_url = _build_url(f"{BUGSNAG_BASE_URL}/organizations/{org_id}/projects", {"per_page": PAGE_SIZE})
        for project in _iter_all_pages(session, projects_url, headers, logger):
            project_id = project["id"]
            parents.append(
                _FanOutParent(
                    resume_id=project_id,
                    path_kwargs={"project_id": project_id},
                    inject={"organization_id": org_id, "project_id": project_id},
                )
            )
    return parents


def _iter_top_level(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[BugsnagResumeConfig],
) -> Iterator[Any]:
    """Paginate a top-level collection (organizations) with resume support."""
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"BugSnag: resuming {config.name} from URL: {url}")
    else:
        url = _build_url(f"{BUGSNAG_BASE_URL}{config.path}", {"per_page": PAGE_SIZE})

    while True:
        items, next_url = _fetch_list_page(session, url, headers, logger)
        # Checkpoint the CURRENT page, not next_url: a chunk can be yielded part-way through this
        # page, so on resume we must re-fetch this page and re-batch every item (merge dedupes the
        # already-yielded ones) rather than skip ahead and drop the items still in the batcher.
        checkpoint_url = url
        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash resumes at this page rather than losing buffered rows.
                manager.save_state(BugsnagResumeConfig(next_url=checkpoint_url))
        if not next_url:
            break
        url = next_url


def _iter_fan_out(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[BugsnagResumeConfig],
) -> Iterator[Any]:
    """Walk every fan-out parent and emit each parent's child rows, injecting parent ids.

    Full refresh: BugSnag's project-scoped list endpoints expose dashboard-style time filters,
    but those aren't verified here, so each sync re-walks every parent. Re-pulled rows on resume
    or re-run dedupe on the composite primary key.
    """
    parents = _resolve_parents(session, headers, config, logger)

    # Resolve the saved parent bookmark to the slice of parents still to process. If the bookmarked
    # parent no longer exists (deleted between runs), start over — merge dedupes the re-pulled rows.
    resume = manager.load_state() if manager.can_resume() else None
    start_index = 0
    resume_url: str | None = None
    if resume is not None and resume.parent_id is not None:
        resume_ids = [parent.resume_id for parent in parents]
        if resume.parent_id in resume_ids:
            start_index = resume_ids.index(resume.parent_id)
            resume_url = resume.next_url
            logger.debug(f"BugSnag: resuming {config.name} fan-out from parent={resume.parent_id}, url={resume_url}")

    for index in range(start_index, len(parents)):
        parent = parents[index]
        path = config.path.format(**parent.path_kwargs)
        url = resume_url or _build_url(f"{BUGSNAG_BASE_URL}{path}", {"per_page": PAGE_SIZE})
        resume_url = None  # only the resumed-into parent uses the saved URL; the rest start fresh

        while True:
            items, next_url = _fetch_list_page(session, url, headers, logger)
            # Checkpoint the CURRENT page (and parent), not next_url. The batcher is shared across
            # parents and can yield part-way through this page, so resume must re-fetch this exact
            # page and re-batch every item (merge dedupes the already-yielded ones). Saving next_url
            # — or advancing the bookmark to the next parent — would skip rows still buffered in the
            # batcher when a crash hits, losing them. We never advance the bookmark past a yielded
            # batch; redundant re-pulls of fully-processed parents are deduped on merge.
            checkpoint_url = url
            for item in items:
                batcher.batch({**item, **parent.inject})
                if batcher.should_yield():
                    yield batcher.get_table()
                    manager.save_state(BugsnagResumeConfig(next_url=checkpoint_url, parent_id=parent.resume_id))
            if not next_url:
                break
            url = next_url


def get_rows(
    auth_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BugsnagResumeConfig],
) -> Iterator[Any]:
    config = BUGSNAG_ENDPOINTS[endpoint]
    headers = _get_headers(auth_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and every fan-out parent) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. Redact the token: it rides in the
    # `Authorization: token …` header under BugSnag's custom scheme, which the tracked transport's
    # built-in scrubber doesn't recognise, so a logged/sampled request would otherwise leak it.
    session = make_tracked_session(redact_values=(auth_token,))

    if config.scope == BugsnagScope.ORGANIZATION:
        yield from _iter_top_level(session, headers, config, logger, batcher, resumable_source_manager)
    else:
        yield from _iter_fan_out(session, headers, config, logger, batcher, resumable_source_manager)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def bugsnag_source(
    auth_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BugsnagResumeConfig],
) -> SourceResponse:
    endpoint_config = BUGSNAG_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            auth_token=auth_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(auth_token: str) -> tuple[bool, str | None]:
    """Confirm the auth token is genuine by listing the organizations it can access.

    The token is org-scoped (not per-endpoint), so a single cheap probe is enough."""
    url = _build_url(f"{BUGSNAG_BASE_URL}/user/organizations", {"per_page": 1})
    try:
        # Redact the token here too — see get_rows() for why BugSnag's custom auth scheme needs it.
        session = make_tracked_session(redact_values=(auth_token,))
        response = session.get(url, headers=_get_headers(auth_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid BugSnag auth token"
    return False, f"BugSnag API error: {response.status_code}"
