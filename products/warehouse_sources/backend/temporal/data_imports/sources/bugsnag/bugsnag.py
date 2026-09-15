import re
import dataclasses
from collections.abc import Callable, Iterator
from itertools import islice
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.settings import (
    BUGSNAG_ENDPOINTS,
    BugsnagEndpointConfig,
    BugsnagScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# BugSnag uses a single global host for its Data Access API. On-prem / Enterprise installs use a
# custom host, which this source does not yet support.
BUGSNAG_BASE_URL = "https://api.bugsnag.com"
# Default per_page for list endpoints. Endpoints that cap lower override it via
# BugsnagEndpointConfig.page_size (e.g. releases, which 400s on anything above 10).
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


@dataclasses.dataclass(frozen=True)
class _FanOutParent:
    # Id used to resolve the endpoint path and to bookmark resume position.
    resume_id: str
    # kwargs passed to ``str.format`` on the endpoint path template.
    path_kwargs: dict[str, str]
    # Parent identifiers injected into every child row so the composite primary key is unique
    # table-wide and the rows are joinable back to their organization/project.
    inject: dict[str, str]
    # Query parameters that identify this parent, for endpoints that scope by parameter rather than
    # by path (release groups take their release stage this way).
    params: dict[str, str] = dataclasses.field(default_factory=dict)


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


def _next_offset_url(url: str, page_len: int) -> str | None:
    """Return the next page URL of an ``offset``-paginated endpoint, or None at the last page.

    BugSnag's performance endpoints page by a numeric row offset and send no Link header, so a
    page shorter than ``per_page`` is the only end-of-data signal available."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    per_page = int(query.get("per_page", ["0"])[0] or 0)
    if per_page <= 0 or page_len < per_page:
        return None
    query["offset"] = [str(int(query.get("offset", ["0"])[0] or 0) + page_len)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


@retry(
    retry=retry_if_exception_type((BugsnagRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    page_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    tolerated_statuses: tuple[int, ...] = (),
):
    response = session.get(page_url, headers=headers, timeout=60)

    # BugSnag rate limits per 1-minute window and returns 429 on exceed; retry those plus
    # transient 5xx. Exponential backoff covers the (typically sub-minute) reset window.
    if response.status_code == 429 or response.status_code >= 500:
        raise BugsnagRetryableError(f"BugSnag API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok and response.status_code not in tolerated_statuses:
        logger.error(f"BugSnag API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response


def _fetch_list_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    tolerated_statuses: tuple[int, ...] = (),
    paginate_by_offset: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one page of a BugSnag list endpoint, returning (items, next_page_url).

    BugSnag list endpoints return a top-level JSON array; the next-page cursor lives in the
    Link header, not the body. The performance endpoints are the exception and page by offset."""
    response = _fetch_page(session, url, headers, logger, tolerated_statuses=tolerated_statuses)
    # A tolerated failure, a 204, or an empty body all mean "nothing here" rather than an error.
    if response.status_code == 204 or not response.ok or not response.content:
        return [], None
    data = response.json()
    if not isinstance(data, list):
        # Defensive: a non-list body has no rows to emit and no cursor to follow.
        return [], None
    if paginate_by_offset:
        return data, _next_offset_url(url, len(data))
    return data, _parse_next_url(response.headers.get("Link", ""))


def _fetch_list_page_or_stop(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    is_first_page: bool,
    tolerated_statuses: tuple[int, ...] = (),
    paginate_by_offset: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """Like `_fetch_list_page`, but ends pagination gracefully at BugSnag's depth ceiling.

    BugSnag's deep list endpoints (errors, events) cap how far pagination can go, yet still emit a
    `next` cursor in the Link header past that ceiling and then reject the very cursor they gave us
    with a 422. That's deterministic — retrying never clears it — so on a follow-up page we treat
    the 422 as end-of-data and keep the rows already pulled rather than failing the whole sync. A
    422 on the first page is left to propagate: BugSnag didn't hand us that cursor."""
    try:
        return _fetch_list_page(
            session,
            url,
            headers,
            logger,
            tolerated_statuses=tolerated_statuses,
            paginate_by_offset=paginate_by_offset,
        )
    except requests.HTTPError as e:
        response = e.response
        if not is_first_page and response is not None and response.status_code == 422:
            logger.warning("BugSnag pagination ceiling reached; stopping this collection early")
            return [], None
        raise


def _endpoint_params(config: BugsnagEndpointConfig, parent: _FanOutParent | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.page_size is not None:
        params["per_page"] = config.page_size
    params.update(config.params)
    if parent is not None:
        params.update(parent.params)
    return params


def _object_rows(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Flatten a single-object endpoint into one row per item of its nested array.

    The object's own scalar fields (e.g. the release stage the trend describes) are copied onto
    every row, so each row stands alone in the warehouse."""
    row_field = config.object_row_field
    if row_field is None:
        return []
    response = _fetch_page(session, url, headers, logger, tolerated_statuses=config.missing_data_statuses)
    # 204 is the documented "this parent has no data yet" answer, and carries no body to parse.
    if response.status_code == 204 or not response.ok or not response.content:
        return []
    data = response.json()
    if not isinstance(data, dict):
        return []
    nested = data.get(row_field) or []
    scalars = {key: value for key, value in data.items() if key != row_field}
    return [{**scalars, **item} for item in nested if isinstance(item, dict)]


def _iter_all_pages(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    paginate_by_offset: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield every item across all pages of a list endpoint, following its next-page cursor."""
    while True:
        items, next_url = _fetch_list_page(session, url, headers, logger, paginate_by_offset=paginate_by_offset)
        yield from items
        if not next_url:
            return
        url = next_url


def _take_capped(
    items: Iterator[dict[str, Any]],
    cap: int | None,
    what: str,
    project_id: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Take at most `cap` fan-out parents, reporting when more were available.

    Reads one item past the cap so the truncation can be logged: a table that quietly covers part
    of a project reads as complete, and each dropped parent is a paginated collection of rows."""
    if cap is None:
        return list(items)
    taken = list(islice(items, cap + 1))
    if len(taken) > cap:
        logger.warning(f"BugSnag: project={project_id} has more than {cap} {what}; syncing the first {cap}")
        return taken[:cap]
    return taken


def _resolve_org_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    url = _build_url(f"{BUGSNAG_BASE_URL}/user/organizations", {"per_page": PAGE_SIZE})
    return [org["id"] for org in _iter_all_pages(session, url, headers, logger)]


def _iter_projects(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (organization_id, project) for every project the token can see."""
    for org_id in _resolve_org_ids(session, headers, logger):
        projects_url = _build_url(f"{BUGSNAG_BASE_URL}/organizations/{org_id}/projects", {"per_page": PAGE_SIZE})
        for project in _iter_all_pages(session, projects_url, headers, logger):
            yield org_id, project


def _project_pivot_display_ids(
    session: requests.Session, headers: dict[str, str], project_id: str, logger: FilteringBoundLogger
) -> list[str]:
    url = _build_url(f"{BUGSNAG_BASE_URL}/projects/{project_id}/pivots", {"per_page": PAGE_SIZE})
    return [pivot["event_field_display_id"] for pivot in _iter_all_pages(session, url, headers, logger)]


def _project_error_ids(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    project_id: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    """The project's errors, most recently seen first, capped for error-grain fan-out.

    The endpoint defaults to `sort=last_seen&direction=desc`, so a capped prefix is the project's
    active errors, which are the ones an error-grain table is worth having rows for."""
    cap = config.max_errors_per_project
    page_size = PAGE_SIZE if cap is None else min(cap + 1, PAGE_SIZE)
    url = _build_url(f"{BUGSNAG_BASE_URL}/projects/{project_id}/errors", {"per_page": page_size})
    errors = _take_capped(_iter_all_pages(session, url, headers, logger), cap, "errors", project_id, logger)
    return [error["id"] for error in errors]


def _project_span_group_ids(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    project_id: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    """The project's span groups, in name order, capped for per-group fan-out."""
    url = _build_url(
        f"{BUGSNAG_BASE_URL}/projects/{project_id}/span_groups",
        {"per_page": PAGE_SIZE, "sort": "name", "direction": "asc"},
    )
    pages = _iter_all_pages(session, url, headers, logger, paginate_by_offset=True)
    groups = _take_capped(pages, config.max_parents_per_project, "span groups", project_id, logger)
    return [group["id"] for group in groups]


def _release_stage_parents(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    project: dict[str, Any],
    inject: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[_FanOutParent]:
    # A project reports the stages it has seen events for; one with none has no release
    # groups to list, and the endpoint rejects a request without a stage.
    project_id = project["id"]
    return [
        _FanOutParent(
            resume_id=f"{project_id}:{stage}",
            path_kwargs={"project_id": project_id},
            inject=inject,
            params={"release_stage_name": stage},
        )
        for stage in project.get("release_stages") or []
    ]


def _pivot_parents(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    project: dict[str, Any],
    inject: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[_FanOutParent]:
    project_id = project["id"]
    return [
        _FanOutParent(
            resume_id=f"{project_id}:{display_id}",
            path_kwargs={"project_id": project_id, "event_field_display_id": display_id},
            inject={**inject, "event_field_display_id": display_id},
        )
        for display_id in _project_pivot_display_ids(session, headers, project_id, logger)
    ]


def _error_parents(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    project: dict[str, Any],
    inject: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[_FanOutParent]:
    project_id = project["id"]
    return [
        _FanOutParent(
            resume_id=f"{project_id}:{error_id}",
            path_kwargs={"project_id": project_id, "error_id": error_id},
            inject={**inject, "error_id": error_id},
        )
        for error_id in _project_error_ids(session, headers, config, project_id, logger)
    ]


def _error_pivot_parents(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    project: dict[str, Any],
    inject: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[_FanOutParent]:
    project_id = project["id"]
    display_ids = _project_pivot_display_ids(session, headers, project_id, logger)
    return [
        _FanOutParent(
            resume_id=f"{project_id}:{error_id}:{display_id}",
            path_kwargs={
                "project_id": project_id,
                "error_id": error_id,
                "event_field_display_id": display_id,
            },
            inject={**inject, "error_id": error_id, "event_field_display_id": display_id},
        )
        for error_id in _project_error_ids(session, headers, config, project_id, logger)
        for display_id in display_ids
    ]


def _span_group_parents(
    session: requests.Session,
    headers: dict[str, str],
    config: BugsnagEndpointConfig,
    project: dict[str, Any],
    inject: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[_FanOutParent]:
    project_id = project["id"]
    return [
        _FanOutParent(
            resume_id=f"{project_id}:{span_group_id}",
            # A span group id is `{version}.{category}.{name}`, and the name can carry slashes
            # (`AppStart/Cold`), so it has to be escaped into the path.
            path_kwargs={"project_id": project_id, "span_group_id": quote(span_group_id, safe="")},
            inject={**inject, "span_group_id": span_group_id},
        )
        for span_group_id in _project_span_group_ids(session, headers, config, project_id, logger)
    ]


# Builders for the scopes that turn one project into several fan-out parents. Every builder takes
# the same arguments so the scope can be dispatched rather than branched on.
_PROJECT_PARENT_BUILDERS: dict[
    BugsnagScope,
    Callable[
        [requests.Session, dict[str, str], BugsnagEndpointConfig, dict[str, Any], dict[str, str], FilteringBoundLogger],
        list[_FanOutParent],
    ],
] = {
    BugsnagScope.PER_PROJECT_RELEASE_STAGE: _release_stage_parents,
    BugsnagScope.PER_PROJECT_PIVOT: _pivot_parents,
    BugsnagScope.PER_PROJECT_ERROR: _error_parents,
    BugsnagScope.PER_PROJECT_ERROR_PIVOT: _error_pivot_parents,
    BugsnagScope.PER_PROJECT_SPAN_GROUP: _span_group_parents,
}


def _resolve_parents(
    session: requests.Session, headers: dict[str, str], config: BugsnagEndpointConfig, logger: FilteringBoundLogger
) -> list[_FanOutParent]:
    """Build the ordered list of fan-out parents for a per-org or per-project endpoint."""
    if config.scope == BugsnagScope.PER_ORG:
        return [
            _FanOutParent(
                resume_id=org_id,
                path_kwargs={"organization_id": org_id},
                inject={"organization_id": org_id},
            )
            for org_id in _resolve_org_ids(session, headers, logger)
        ]

    parents: list[_FanOutParent] = []
    for org_id, project in _iter_projects(session, headers, logger):
        project_id = project["id"]
        inject = {"organization_id": org_id, "project_id": project_id}

        if config.scope == BugsnagScope.PER_PROJECT:
            parents.append(_FanOutParent(resume_id=project_id, path_kwargs={"project_id": project_id}, inject=inject))
            continue

        build_parents = _PROJECT_PARENT_BUILDERS[config.scope]
        project_parents = build_parents(session, headers, config, project, inject, logger)

        cap = config.max_parents_per_project
        if cap is not None and len(project_parents) > cap:
            # Each parent is a paginated collection of its own, so an inflated count turns one
            # project into an unbounded sync. Take a deterministic prefix and say so.
            logger.warning(
                f"BugSnag: project={project_id} offers {len(project_parents)} fan-out parents for "
                f"{config.name}; syncing the first {cap}"
            )
            project_parents = project_parents[:cap]
        parents.extend(project_parents)
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
        url = _build_url(f"{BUGSNAG_BASE_URL}{config.path}", _endpoint_params(config))

    first_page = True
    while True:
        items, next_url = _fetch_list_page_or_stop(
            session,
            url,
            headers,
            logger,
            is_first_page=first_page,
            tolerated_statuses=config.missing_data_statuses,
            paginate_by_offset=config.paginate_by_offset,
        )
        first_page = False
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
        params = _endpoint_params(config, parent)
        url = resume_url or _build_url(f"{BUGSNAG_BASE_URL}{path}", params)
        resume_url = None  # only the resumed-into parent uses the saved URL; the rest start fresh

        if config.object_row_field is not None:
            for item in _object_rows(session, url, headers, config, logger):
                batcher.batch({**item, **parent.inject})
                if batcher.should_yield():
                    yield batcher.get_table()
                    manager.save_state(BugsnagResumeConfig(next_url=None, parent_id=parent.resume_id))
            continue

        page_count = 0
        while True:
            items, next_url = _fetch_list_page_or_stop(
                session,
                url,
                headers,
                logger,
                is_first_page=page_count == 0,
                tolerated_statuses=config.missing_data_statuses,
                paginate_by_offset=config.paginate_by_offset,
            )
            page_count += 1
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
            if config.max_pages is not None and page_count >= config.max_pages:
                logger.warning(
                    f"BugSnag: page cap reached for {config.name} on parent={parent.resume_id}; "
                    "stopping this collection early"
                )
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
