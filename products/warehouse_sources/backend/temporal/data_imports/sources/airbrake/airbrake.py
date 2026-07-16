import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.settings import (
    AIRBRAKE_ENDPOINTS,
    AirbrakeEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AIRBRAKE_BASE_URL = "https://api.airbrake.io"
PAGE_LIMIT = 100
# Page/limit pagination has no cursor, so a server that ignored `page` would loop forever
# on the same items. This cap is a safety valve, far above any realistic collection size.
MAX_PAGES_PER_COLLECTION = 10_000
# Notices are the unbounded fan-out (every occurrence of every error group); cap the history
# pulled per group so one noisy group can't dominate the sync.
NOTICES_MAX_PAGES_PER_GROUP = 20


class AirbrakeRetryableError(Exception):
    pass


@dataclasses.dataclass
class AirbrakeResumeConfig:
    # Next page to fetch within the current collection.
    page: int = 1
    # Stable parent bookmarks (not positional indexes), so projects/groups added or removed
    # between a crash and the retry can't resume us into the wrong parent.
    project_id: int | None = None
    group_id: str | None = None


def _format_start_time(value: Any) -> str:
    """Format an incremental cursor as the RFC 3339 UTC timestamp Airbrake expects."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_start_time(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


@retry(
    retry=retry_if_exception_type(
        (
            AirbrakeRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=60)

    # Airbrake returns 429 on quota exhaustion; explicit request rate limits aren't documented.
    if response.status_code == 429 or response.status_code >= 500:
        raise AirbrakeRetryableError(f"Airbrake API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during fan-out (a project/group deleted mid-sync) and handled by callers.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Airbrake API error: status={response.status_code}, body={response.text}, url={url}")
        # Not raise_for_status(): its message embeds response.url, which carries the ?key=
        # credential, and the message is persisted into job errors and logs. `url` is query-free.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {url}", response=response
        )

    return response.json()


def _iter_pages(
    session: requests.Session,
    api_key: str,
    path: str,
    collection_key: str,
    logger: FilteringBoundLogger,
    params: Optional[dict[str, Any]] = None,
    start_page: int = 1,
    max_pages: int = MAX_PAGES_PER_COLLECTION,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Walk a page/limit-paginated collection, yielding (page_number, items) per page.

    Termination is driven by an empty page rather than `len(items) < limit`: the docs state no
    maximum for `limit`, so a server silently clamping our requested page size below PAGE_LIMIT
    must not be mistaken for the final page.
    """
    page = start_page
    while True:
        if page - start_page + 1 > max_pages:
            logger.warning(f"Airbrake: page cap ({max_pages}) reached for {path}, truncating collection")
            break

        data = _fetch_page(
            session,
            f"{AIRBRAKE_BASE_URL}{path}",
            {"key": api_key, "limit": PAGE_LIMIT, "page": page, **(params or {})},
            logger,
        )
        items = data.get(collection_key) or []
        if not items:
            break

        yield page, items

        # When the whole collection fits in the first page, `count` lets us skip the
        # trailing empty-page request.
        count = data.get("count")
        if page == 1 and start_page == 1 and isinstance(count, int) and count <= len(items):
            break
        page += 1


def _list_projects(session: requests.Session, api_key: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    return [
        item for _page, items in _iter_pages(session, api_key, "/api/v4/projects", "projects", logger) for item in items
    ]


def _load_resume(manager: ResumableSourceManager[AirbrakeResumeConfig]) -> AirbrakeResumeConfig | None:
    return manager.load_state() if manager.can_resume() else None


def _is_not_found(exc: requests.HTTPError) -> bool:
    return exc.response is not None and exc.response.status_code == 404


def _projects_rows(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AirbrakeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = _load_resume(manager)
    start_page = resume.page if resume else 1

    for page, items in _iter_pages(session, api_key, "/api/v4/projects", "projects", logger, start_page=start_page):
        yield items
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
        manager.save_state(AirbrakeResumeConfig(page=page + 1))


def _slice_from_bookmark(items: list[Any], bookmark: Any) -> tuple[list[Any], bool]:
    """Return the slice starting at `bookmark` (or the full list when it's gone) and whether it matched."""
    if bookmark is not None and bookmark in items:
        return items[items.index(bookmark) :], True
    return items, False


def _project_fan_out_rows(
    session: requests.Session,
    api_key: str,
    endpoint_config: AirbrakeEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AirbrakeResumeConfig],
    params: Optional[dict[str, Any]] = None,
    inject_project_id: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out one paginated collection request per project (groups, deploys)."""
    project_ids = [project["id"] for project in _list_projects(session, api_key, logger)]

    resume = _load_resume(manager)
    remaining, resumed = _slice_from_bookmark(project_ids, resume.project_id if resume else None)
    resume_page = resume.page if resume is not None and resumed else 1

    for index, project_id in enumerate(remaining):
        path = endpoint_config.path.format(project_id=project_id)
        start_page = resume_page if index == 0 else 1

        try:
            for page, items in _iter_pages(
                session, api_key, path, endpoint_config.collection_key, logger, params=params, start_page=start_page
            ):
                if inject_project_id:
                    items = [{**item, "projectId": project_id} for item in items]
                yield items
                manager.save_state(AirbrakeResumeConfig(page=page + 1, project_id=project_id))
        except requests.HTTPError as exc:
            # A project deleted between enumeration and this fetch 404s; its data is genuinely
            # gone, so skip it rather than failing the whole sync.
            if _is_not_found(exc):
                logger.warning(f"Airbrake: project {project_id} not found while fetching {endpoint_config.name}")
            else:
                raise

        if index + 1 < len(remaining):
            manager.save_state(AirbrakeResumeConfig(page=1, project_id=remaining[index + 1]))


def _list_group_ids(
    session: requests.Session, api_key: str, project_id: int, logger: FilteringBoundLogger
) -> list[str]:
    return [
        group["id"]
        for _page, items in _iter_pages(
            session, api_key, f"/api/v4/projects/{project_id}/groups", "groups", logger, params={"order": "created"}
        )
        for group in items
    ]


def _notices_rows(
    session: requests.Session,
    api_key: str,
    endpoint_config: AirbrakeEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AirbrakeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Two-level fan-out: every error group of every project, then that group's notices."""
    project_ids = [project["id"] for project in _list_projects(session, api_key, logger)]

    resume = _load_resume(manager)
    remaining_projects, resumed_project = _slice_from_bookmark(project_ids, resume.project_id if resume else None)

    for project_index, project_id in enumerate(remaining_projects):
        try:
            group_ids = _list_group_ids(session, api_key, project_id, logger)
        except requests.HTTPError as exc:
            if _is_not_found(exc):
                logger.warning(f"Airbrake: project {project_id} not found while enumerating groups")
                continue
            raise

        resume_this_project = project_index == 0 and resumed_project
        remaining_groups, resumed_group = _slice_from_bookmark(
            group_ids, resume.group_id if resume is not None and resume_this_project else None
        )

        for group_index, group_id in enumerate(remaining_groups):
            start_page = resume.page if resume is not None and resumed_group and group_index == 0 else 1
            path = endpoint_config.path.format(project_id=project_id, group_id=group_id)

            try:
                for page, items in _iter_pages(
                    session,
                    api_key,
                    path,
                    endpoint_config.collection_key,
                    logger,
                    start_page=start_page,
                    max_pages=NOTICES_MAX_PAGES_PER_GROUP,
                ):
                    yield items
                    manager.save_state(AirbrakeResumeConfig(page=page + 1, project_id=project_id, group_id=group_id))
            except requests.HTTPError as exc:
                if _is_not_found(exc):
                    logger.warning(f"Airbrake: group {group_id} in project {project_id} not found, skipping notices")
                else:
                    raise

            if group_index + 1 < len(remaining_groups):
                manager.save_state(
                    AirbrakeResumeConfig(page=1, project_id=project_id, group_id=remaining_groups[group_index + 1])
                )

        if project_index + 1 < len(remaining_projects):
            manager.save_state(AirbrakeResumeConfig(page=1, project_id=remaining_projects[project_index + 1]))


def _build_groups_params(
    should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]
) -> dict[str, Any]:
    # `created` is the one immutable sort key, keeping page boundaries stable while new
    # notices arrive mid-sync (the default `last_notice` order reshuffles groups between pages).
    params: dict[str, Any] = {"order": "created"}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # start_time is a server-side filter on group creation time.
        params["start_time"] = _format_start_time(db_incremental_field_last_value)
    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AirbrakeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AIRBRAKE_ENDPOINTS[endpoint]
    # One session reused across every page and parent so the connection stays alive.
    session = make_tracked_session()

    if endpoint == "projects":
        yield from _projects_rows(session, api_key, logger, resumable_source_manager)
    elif endpoint == "groups":
        yield from _project_fan_out_rows(
            session,
            api_key,
            endpoint_config,
            logger,
            resumable_source_manager,
            params=_build_groups_params(should_use_incremental_field, db_incremental_field_last_value),
        )
    elif endpoint == "deploys":
        # Deploy rows don't reference their project, so stamp projectId on for joinability.
        yield from _project_fan_out_rows(
            session, api_key, endpoint_config, logger, resumable_source_manager, inject_project_id=True
        )
    elif endpoint == "notices":
        yield from _notices_rows(session, api_key, endpoint_config, logger, resumable_source_manager)
    else:
        raise ValueError(f"Unknown Airbrake endpoint: {endpoint}")


def airbrake_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AirbrakeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = AIRBRAKE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Fan-out endpoints persist the incremental watermark only at successful job end (desc
        # mode): a partial run's max says nothing about projects it never reached. Airbrake also
        # doesn't document the direction of its `order` sorts, so per-batch asc checkpointing
        # can't be trusted for the top-level list either.
        sort_mode="desc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    try:
        response = make_tracked_session().get(
            f"{AIRBRAKE_BASE_URL}/api/v4/projects",
            params={"key": api_key, "limit": "1"},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False
