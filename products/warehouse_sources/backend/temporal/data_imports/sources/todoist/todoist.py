import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import (
    TODOIST_BASE_URL,
    TODOIST_ENDPOINTS,
    TodoistEndpointConfig,
)

# Todoist caps list endpoints at 200 items per page. Verified against the published API docs, not a
# live token — the paginator follows `next_cursor` regardless, so an over-large value would only ever
# cost an extra round trip if the cap turns out lower.
PAGE_LIMIT = 200

# Bound retries deterministically (5 attempts) so a wedged endpoint fails cleanly instead of spinning.
MAX_RETRIES = 5


class TodoistRetryableError(Exception):
    pass


@dataclasses.dataclass
class TodoistResumeConfig:
    # Body cursor for the next page. None means "start at the first page".
    next_cursor: str | None = None
    # The project currently being processed during the collaborators fan-out. A stable project-ID
    # bookmark (not a positional index) so projects added/removed between a crash and the retry can't
    # resume us into the wrong project. None for the standard (non-fan-out) endpoints.
    project_id: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    base = f"{TODOIST_BASE_URL}{path}"
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def validate_credentials(api_token: str) -> bool:
    # Cheapest authenticated probe: pull a single project. A genuine token returns 200; a bad/revoked
    # one returns 401. Network/DNS/timeout failures are intentionally not caught here so they
    # propagate rather than being misreported to the user as an invalid credential.
    url = _build_url("/projects", {"limit": 1})
    response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
    return response.status_code == 200


@retry(
    retry=retry_if_exception_type((TodoistRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict | list:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limit) and 5xx are transient — let tenacity back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise TodoistRetryableError(f"Todoist API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Todoist API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _parse_page(data: dict | list) -> tuple[list[dict], str | None]:
    """Normalize a Todoist v1 list response into (rows, next_cursor).

    The unified v1 API wraps lists as ``{"results": [...], "next_cursor": "..."}``. Some endpoints
    historically returned a bare array; handle both so the source is robust to either shape.
    """
    if isinstance(data, list):
        return data, None
    results = data.get("results", [])
    return results, data.get("next_cursor")


def _iter_project_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through /projects and yield each project's id, following the body cursor."""
    url = _build_url("/projects", {"limit": PAGE_LIMIT})
    while True:
        data = _fetch_page(session, url, headers, logger)
        rows, next_cursor = _parse_page(data)
        for item in rows:
            yield item["id"]

        if not next_cursor:
            break
        url = _build_url("/projects", {"limit": PAGE_LIMIT, "cursor": next_cursor})


def _get_collaborator_rows(
    config: TodoistEndpointConfig,
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
) -> Iterator[list[dict]]:
    """Fan out over every project, materializing project<->collaborator membership.

    Each collaborator row gets the owning ``project_id`` injected so the composite primary key
    ``[project_id, id]`` stays unique table-wide. Full refresh only — there is no server-side
    incremental filter — so re-pulled rows on resume are deduped by the primary key on merge.
    """
    project_ids = list(_iter_project_ids(session, headers, logger))

    # Resolve the saved project-ID bookmark to the slice of projects still to process. If the
    # bookmarked project no longer exists (deleted between runs), start over from the first project —
    # merge dedupes the re-pulled rows on the primary key. `resume_cursor` is consumed by the first
    # project only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = project_ids
    resume_cursor: str | None = None
    if resume is not None and resume.project_id is not None and resume.project_id in project_ids:
        remaining = project_ids[project_ids.index(resume.project_id) :]
        resume_cursor = resume.next_cursor
        logger.debug(f"Todoist: resuming collaborators from project_id={resume.project_id}, cursor={resume_cursor}")

    for index, project_id in enumerate(remaining):
        path = config.path.replace("{project_id}", project_id)
        cursor = resume_cursor
        resume_cursor = None  # only the resumed-into project uses the saved cursor; the rest start fresh

        try:
            while True:
                params: dict[str, Any] = {"limit": PAGE_LIMIT}
                if cursor:
                    params["cursor"] = cursor
                data = _fetch_page(session, _build_url(path, params), headers, logger)
                rows, next_cursor = _parse_page(data)

                if rows:
                    yield [{**row, "project_id": project_id} for row in rows]
                    # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
                    # last page rather than skipping it — merge dedupes on the primary key.
                    if next_cursor:
                        resumable_source_manager.save_state(
                            TodoistResumeConfig(next_cursor=next_cursor, project_id=project_id)
                        )

                if not next_cursor:
                    break
                cursor = next_cursor
        except requests.HTTPError as exc:
            # A project deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — the membership is genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Todoist: project {project_id} not found while fetching collaborators, skipping")
            else:
                raise

        # Advance the bookmark to the next project so a crash between projects resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(TodoistResumeConfig(next_cursor=None, project_id=remaining[index + 1]))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
) -> Iterator[list[dict]]:
    config = TODOIST_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page (and, for fan-out, every project) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    if config.fan_out_over_projects:
        yield from _get_collaborator_rows(config, session, headers, logger, resumable_source_manager)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None
    if cursor:
        logger.debug(f"Todoist: resuming {endpoint} from cursor={cursor}")

    while True:
        params: dict[str, Any] = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        rows, next_cursor = _parse_page(data)

        if rows:
            yield rows
            if next_cursor:
                resumable_source_manager.save_state(TodoistResumeConfig(next_cursor=next_cursor))

        if not next_cursor:
            break
        cursor = next_cursor


def todoist_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
) -> SourceResponse:
    endpoint_config = TODOIST_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


__all__ = ["TodoistResumeConfig", "get_rows", "todoist_source", "validate_credentials"]
