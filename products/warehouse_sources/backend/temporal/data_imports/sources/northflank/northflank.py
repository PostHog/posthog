from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import reach_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.settings import (
    FAN_OUT_PARENTS,
    NORTHFLANK_ENDPOINTS,
    NorthflankEndpointConfig,
)

NORTHFLANK_BASE_URL = "https://api.northflank.com"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Northflank paginates at up to 100 results per page (defaults to 50 if unset).
PAGE_SIZE = 100
# Guardrails against an unbounded scan. The 1000 req/hour account rate limit makes deep fan-out
# expensive, so bound both the project scan and each project's child scan by pages.
MAX_PROJECT_PAGES = 500
MAX_CHILD_PAGES_PER_PROJECT = 500
# The API asks us to wait via rate-limit headers on a 429; clamp anything absurd.
MAX_RATE_LIMIT_SLEEP_SECONDS = 120


@frozen
class NorthflankResumeConfig:
    # Next page of the list in progress. None means that list is done.
    cursor: str | None = None
    # Fan-out position. `parent_id` is set only for endpoints that fan out over a second level, and
    # `stage` only for endpoints queried once per pipeline stage.
    project_id: str | None = None
    parent_id: str | None = None
    stage: str | None = None


class NorthflankRetryableError(Exception):
    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        # Seconds the API asked us to wait (from Retry-After/x-ratelimit-reset); 0 when unknown.
        self.retry_after = retry_after


FetchPageFn = Callable[[str], dict[str, Any]]

_EXPONENTIAL_WAIT = wait_exponential_jitter(initial=1, max=60)


def _retry_wait(retry_state: RetryCallState) -> float:
    # Honor the API's reset hint once; otherwise back off exponentially. Doing the wait here (rather
    # than sleeping inside fetch_page) avoids stacking both delays.
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, NorthflankRetryableError) and exc.retry_after:
        return exc.retry_after
    return _EXPONENTIAL_WAIT(retry_state)


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    clean_params = {key: value for key, value in (params or {}).items() if value is not None}
    if not clean_params:
        return f"{NORTHFLANK_BASE_URL}{path}"
    return f"{NORTHFLANK_BASE_URL}{path}?{urlencode(clean_params)}"


def _rate_limit_sleep_seconds(response: requests.Response) -> int:
    # `x-ratelimit-reset` is documented as time-to-reset in seconds; prefer a Retry-After if present.
    for header in ("retry-after", "x-ratelimit-reset"):
        raw = response.headers.get(header)
        if raw is None:
            continue
        try:
            seconds = int(float(raw))
        except (TypeError, ValueError):
            continue
        return max(0, min(seconds, MAX_RATE_LIMIT_SLEEP_SECONDS))
    return 0


def _extract_rows(body: dict[str, Any], data_key: str) -> list[dict[str, Any]]:
    """Pull the row array out of Northflank's `{"data": {...}}` envelope.

    List endpoints nest the array under `data.<resource>` (e.g. `data.projects`). We also tolerate
    `data` being the array itself, since the API reference is inconsistent on this for some
    endpoints and we can't curl-verify every one.
    """
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get(data_key)
        if isinstance(rows, list):
            return rows
    return []


def _next_cursor(body: dict[str, Any]) -> str | None:
    pagination = body.get("pagination") or {}
    if not pagination.get("hasNextPage"):
        return None
    return pagination.get("cursor")


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the token by listing projects (the resource every stream depends on)."""
    # Disable the adapter's urllib3 retry layer: an already rate-limited token would otherwise make
    # validation block the worker for the provider's full (uncapped) Retry-After. Fail fast instead.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_token,))
    try:
        response = session.get(
            _build_url("/v1/projects", {"per_page": 1}),
            headers=_get_headers(api_token),
            timeout=10,
        )
    except Exception:
        return False, "Could not reach the Northflank API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Northflank API token. Please check that your token is valid and not revoked."
    return False, f"Northflank API returned an unexpected status: {response.status_code}."


def _make_fetch_page(api_token: str, logger: FilteringBoundLogger) -> FetchPageFn:
    headers = _get_headers(api_token)
    # One session reused across pages/retries so connection pooling and per-session tracking hold;
    # redact_values masks the token in logs and captured samples. retry=Retry(total=0) disables the
    # adapter's urllib3 retry layer so the tenacity policy below is the only one — otherwise urllib3
    # would retry 429/5xx underneath it, honoring an uncapped Retry-After and stacking retry layers,
    # bypassing this connector's capped rate-limit backoff.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_token,))

    @retry_with_deadline(
        retry=retry_if_exception_type((NorthflankRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(url: str) -> dict[str, Any]:
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429:
            sleep_seconds = _rate_limit_sleep_seconds(response)
            logger.debug(f"Northflank: rate limited, retrying after {sleep_seconds}s. url={url}")
            raise NorthflankRetryableError(
                f"Northflank API rate limited: status=429, url={url}", retry_after=sleep_seconds
            )

        if response.status_code >= 500:
            raise NorthflankRetryableError(
                f"Northflank API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            if response.status_code != 404:
                logger.error(f"Northflank API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def _iter_pages(
    fetch_page: FetchPageFn,
    path: str,
    logger: FilteringBoundLogger,
    max_pages: int,
    resource: str,
    data_key: str,
    params: dict[str, Any] | None = None,
    page_size_param: str = "per_page",
    paginated: bool = True,
    start_cursor: str | None = None,
    checkpoint: Callable[[str | None], None] | None = None,
    not_found_is_empty: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    """Yield each page's rows for a cursor-paginated list endpoint.

    `checkpoint` receives the cursor of the next page (None after the last page) before the page's
    rows are yielded.
    """
    cursor = start_cursor
    pages_fetched = 0

    while True:
        page_params = dict(params or {})
        if paginated:
            page_params.update({page_size_param: PAGE_SIZE, "cursor": cursor})
        try:
            body = fetch_page(_build_url(path, page_params))
        except requests.HTTPError as e:
            if not (not_found_is_empty and e.response is not None and e.response.status_code == 404):
                raise
            body = {}
        pages_fetched += 1

        rows = _extract_rows(body, data_key)
        next_cursor = _next_cursor(body) if paginated else None
        if next_cursor and pages_fetched >= max_pages:
            logger.warning(
                f"Northflank: page cap reached for {resource}, stopping pagination. max_pages={max_pages}, path={path}"
            )
            next_cursor = None

        if checkpoint:
            checkpoint(next_cursor)
        if rows:
            yield rows
        else:
            # Fan-out over parents with no children can otherwise make long runs of empty requests.
            reach_safe_point()

        if not next_cursor:
            return
        cursor = next_cursor


def _iter_ids(pages: Iterator[list[dict[str, Any]]], resource: str) -> Iterator[tuple[str, dict[str, Any]]]:
    for page in pages:
        for row in page:
            row_id = row.get("id")
            if not row_id:
                # A parent without an id would silently drop all of its nested resources, leaving a
                # partial import. Fail loudly instead.
                raise ValueError(f"Northflank: {resource} is missing a required 'id' field: {row!r}")
            yield row_id, row


def _skip_to(
    ids: Iterator[tuple[str, dict[str, Any]]], target: str | None, logger: FilteringBoundLogger, resource: str
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Drop ids before `target`, the position a resumed run continues from."""
    if target is None:
        yield from ids
        return
    found = False
    for row_id, row in ids:
        if not found and row_id != target:
            continue
        found = True
        yield row_id, row
    if not found:
        logger.warning(f"Northflank: resume position {resource} {target} no longer exists, nothing left to sync")


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    incremental_start: Optional[int] = None,
    resumable_source_manager: Optional[ResumableSourceManager[NorthflankResumeConfig]] = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in NORTHFLANK_ENDPOINTS:
        raise ValueError(f"Unknown Northflank endpoint: {endpoint}")

    config = NORTHFLANK_ENDPOINTS[endpoint]
    fetch_page = _make_fetch_page(api_token, logger)
    manager = resumable_source_manager
    resume = manager.load_state() if manager is not None and manager.can_resume() else None

    def checkpoint_at(
        project_id: str | None = None, parent_id: str | None = None, stage: str | None = None
    ) -> Callable[[str | None], None]:
        def checkpoint(next_cursor: str | None) -> None:
            if manager is not None:
                manager.save_state(
                    NorthflankResumeConfig(cursor=next_cursor, project_id=project_id, parent_id=parent_id, stage=stage)
                )

        return checkpoint

    if not config.fan_out_over_projects:
        if resume is not None and resume.cursor is None:
            return
        params = dict(config.params)
        if config.incremental_param:
            # Without a start time the API does not document how far back hourly entries go, so a
            # full refresh asks for everything since the epoch.
            params[config.incremental_param] = incremental_start if incremental_start is not None else 0
        yield from _iter_pages(
            fetch_page,
            config.path,
            logger,
            max_pages=MAX_PROJECT_PAGES,
            resource=endpoint,
            data_key=config.data_key,
            params=params,
            page_size_param=config.page_size_param,
            paginated=config.paginated,
            start_cursor=resume.cursor if resume else None,
            checkpoint=checkpoint_at(),
        )
        return

    projects = _iter_ids(
        _iter_pages(
            fetch_page, "/v1/projects", logger, max_pages=MAX_PROJECT_PAGES, resource="projects", data_key="projects"
        ),
        "project",
    )
    for project_id, _ in _skip_to(projects, resume.project_id if resume else None, logger, "project"):
        resuming_project = resume is not None and resume.project_id == project_id

        if not config.parent:
            if resuming_project and resume is not None and resume.cursor is None:
                continue
            for rows in _iter_pages(
                fetch_page,
                config.path.format(project_id=project_id),
                logger,
                max_pages=MAX_CHILD_PAGES_PER_PROJECT,
                resource=f"{endpoint} of project {project_id}",
                data_key=config.data_key,
                start_cursor=resume.cursor if resuming_project and resume is not None else None,
                checkpoint=checkpoint_at(project_id),
            ):
                # Inject the parent project id so the composite primary key is present even on child
                # objects that don't carry it natively (addons, volumes).
                yield [{**row, "projectId": project_id} for row in rows]
            continue

        yield from _iter_parent_children(
            fetch_page, config, project_id, logger, resume if resuming_project else None, checkpoint_at
        )


def _iter_parent_children(
    fetch_page: FetchPageFn,
    config: NorthflankEndpointConfig,
    project_id: str,
    logger: FilteringBoundLogger,
    resume: NorthflankResumeConfig | None,
    checkpoint_at: Callable[[str | None, str | None, str | None], Callable[[str | None], None]],
) -> Iterator[list[dict[str, Any]]]:
    if not config.parent or not config.parent_id_key:
        raise ValueError(f"Northflank endpoint {config.name} has no parent to fan out over")
    parent_config = FAN_OUT_PARENTS[config.parent]
    parent_id_key = config.parent_id_key

    parents = _iter_ids(
        _iter_pages(
            fetch_page,
            parent_config.path.format(project_id=project_id),
            logger,
            max_pages=MAX_CHILD_PAGES_PER_PROJECT,
            resource=f"{config.parent} of project {project_id}",
            data_key=parent_config.data_key,
        ),
        config.parent,
    )
    resume_parent_id = resume.parent_id if resume else None
    all_stages: tuple[str | None, ...] = config.stages or (None,)
    for parent_id, parent in _skip_to(parents, resume_parent_id, logger, config.parent):
        if config.include_parent and not config.include_parent(parent):
            continue
        resume_in_parent = resume if resume is not None and parent_id == resume_parent_id else None
        stages = all_stages
        if resume_in_parent is not None and resume_in_parent.stage in all_stages:
            stages = all_stages[all_stages.index(resume_in_parent.stage) :]
        for stage in stages:
            start_cursor: str | None = None
            if resume_in_parent is not None and stage == resume_in_parent.stage:
                if resume_in_parent.cursor is None:
                    continue
                start_cursor = resume_in_parent.cursor
            stage_column = {"stage": stage} if stage is not None else {}
            for rows in _iter_pages(
                fetch_page,
                config.path.format(project_id=project_id, parent_id=parent_id, stage=stage),
                logger,
                max_pages=MAX_CHILD_PAGES_PER_PROJECT,
                resource=f"{config.name} of {config.parent} {parent_id} in project {project_id}",
                data_key=config.data_key,
                start_cursor=start_cursor,
                checkpoint=checkpoint_at(project_id, parent_id, stage),
                not_found_is_empty=config.not_found_is_empty,
            ):
                yield [{**row, "projectId": project_id, parent_id_key: parent_id, **stage_column} for row in rows]


def northflank_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    incremental_start: Optional[int] = None,
    resumable_source_manager: Optional[ResumableSourceManager[NorthflankResumeConfig]] = None,
) -> SourceResponse:
    config = NORTHFLANK_ENDPOINTS[endpoint]
    partition_key: Optional[str] = config.partition_key

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            incremental_start=incremental_start,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
