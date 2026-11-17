import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.airbrake.settings import (
    AIRBRAKE_ENDPOINTS,
    AirbrakeEndpointConfig,
    AirbrakeStatsConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    retry_with_deadline,
)

AIRBRAKE_BASE_URL = "https://api.airbrake.io"
PAGE_LIMIT = 100
# Page/limit pagination has no cursor, so a server that ignored `page` would loop forever
# on the same items. This cap is a safety valve, far above any realistic collection size.
MAX_PAGES_PER_COLLECTION = 10_000
# Notices are the unbounded fan-out (every occurrence of every error group); cap the history
# pulled per group so one noisy group can't dominate the sync.
NOTICES_MAX_PAGES_PER_GROUP = 20
# Per-group and per-collection caps bound each child request, but not the two-level fan-out as a
# whole: an account with a huge number of error groups would otherwise keep an import worker busy
# for the full activity timeout. Bound the total groups a single notice sync fans out into — a
# safety valve far above any realistic account, not an expected limit.
NOTICES_MAX_GROUPS_PER_SYNC = 10_000
# Group stats fan out over the same groups as notices, so they get the same safety valve.
GROUP_STATS_MAX_GROUPS_PER_SYNC = 10_000
# Stats endpoints return at most `limit` buckets (documented default 100). Each request asks for a
# window that holds no more buckets than this, so no bucket is cut off.
STATS_BUCKETS_PER_REQUEST = 100


class AirbrakeRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
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


@retry_with_deadline(
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

    groups_fanned_out = 0
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
            if groups_fanned_out >= NOTICES_MAX_GROUPS_PER_SYNC:
                logger.warning(
                    f"Airbrake: notice group budget ({NOTICES_MAX_GROUPS_PER_SYNC}) reached, stopping notice sync"
                )
                return
            groups_fanned_out += 1

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


def _now() -> datetime:
    return datetime.now(UTC)


def _to_epoch_seconds(value: Any) -> int | None:
    if isinstance(value, datetime):
        return int((value.replace(tzinfo=UTC) if value.tzinfo is None else value).timestamp())
    if isinstance(value, date):
        return _to_epoch_seconds(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    if isinstance(value, str):
        try:
            return _to_epoch_seconds(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _stats_windows(
    stats: AirbrakeStatsConfig, now: datetime, db_incremental_field_last_value: Optional[Any]
) -> list[tuple[int, int | None]]:
    """Split the read range into [time__gte, time__lt) windows of epoch seconds.

    The range starts at the lookback limit, or at the watermark when that is later. The watermark is
    the newest bucket already loaded, which was possibly still filling, so the range includes it again.
    The last window has no upper bound and ends at the current, partial bucket.
    """
    now_seconds = int(now.timestamp())
    start = now_seconds - stats.lookback_seconds
    watermark = _to_epoch_seconds(db_incremental_field_last_value)
    if watermark is not None:
        start = max(start, watermark)
    start -= start % stats.period_seconds

    span = STATS_BUCKETS_PER_REQUEST * stats.period_seconds
    windows: list[tuple[int, int | None]] = []
    while start + span <= now_seconds:
        windows.append((start, start + span))
        start += span
    windows.append((start, None))
    return windows


def _stats_rows_from_response(data: dict[str, Any], parent: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn Airbrake's parallel arrays ({"time": [...], "accepted": [...]}) into one row per bucket."""
    times = data.get("time") or []
    series = {key: values for key, values in data.items() if key != "time" and isinstance(values, list)}
    rows = []
    for index, bucket in enumerate(times):
        if bucket is None:
            continue
        row: dict[str, Any] = {**parent, "time": bucket}
        for key, values in series.items():
            row[key] = values[index] if index < len(values) else None
        rows.append(row)
    return rows


def _stats_series_rows(
    session: requests.Session,
    api_key: str,
    path: str,
    stats: AirbrakeStatsConfig,
    windows: list[tuple[int, int | None]],
    parent: dict[str, Any],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AirbrakeResumeConfig],
    current: AirbrakeResumeConfig,
    following: AirbrakeResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    """Read every window of one parent's stats, staging where a resumed run must continue.

    Windows are cheap compared to the parent enumeration, so a resume restarts the current parent.
    After the last window it continues at `following`.
    """
    for index, (start, end) in enumerate(windows):
        params: dict[str, Any] = {
            "key": api_key,
            "period": stats.period,
            "time__gte": start,
            "limit": STATS_BUCKETS_PER_REQUEST,
        }
        if end is not None:
            params["time__lt"] = end
        rows = _stats_rows_from_response(_fetch_page(session, f"{AIRBRAKE_BASE_URL}{path}", params, logger), parent)

        bookmark = following if index + 1 == len(windows) else current
        if bookmark is not None:
            manager.save_state(bookmark)
        if rows:
            yield rows
        else:
            manager.safe_point()


def _project_stats_rows(
    session: requests.Session,
    api_key: str,
    endpoint_config: AirbrakeEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AirbrakeResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    assert endpoint_config.stats is not None
    windows = _stats_windows(endpoint_config.stats, _now(), db_incremental_field_last_value)
    project_ids = [project["id"] for project in _list_projects(session, api_key, logger)]

    resume = _load_resume(manager)
    remaining, _resumed = _slice_from_bookmark(project_ids, resume.project_id if resume else None)

    for index, project_id in enumerate(remaining):
        following = AirbrakeResumeConfig(project_id=remaining[index + 1]) if index + 1 < len(remaining) else None
        try:
            yield from _stats_series_rows(
                session,
                api_key,
                endpoint_config.path.format(project_id=project_id),
                endpoint_config.stats,
                windows,
                {"projectId": project_id},
                logger,
                manager,
                current=AirbrakeResumeConfig(project_id=project_id),
                following=following,
            )
        except requests.HTTPError as exc:
            if not _is_not_found(exc):
                raise
            logger.warning(f"Airbrake: project {project_id} not found while fetching {endpoint_config.name}")
            manager.safe_point()


def _group_stats_rows(
    session: requests.Session,
    api_key: str,
    endpoint_config: AirbrakeEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AirbrakeResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    assert endpoint_config.stats is not None
    windows = _stats_windows(endpoint_config.stats, _now(), db_incremental_field_last_value)
    project_ids = [project["id"] for project in _list_projects(session, api_key, logger)]

    resume = _load_resume(manager)
    remaining_projects, resumed_project = _slice_from_bookmark(project_ids, resume.project_id if resume else None)

    groups_fanned_out = 0
    for project_index, project_id in enumerate(remaining_projects):
        try:
            group_ids = _list_group_ids(session, api_key, project_id, logger)
        except requests.HTTPError as exc:
            if not _is_not_found(exc):
                raise
            logger.warning(f"Airbrake: project {project_id} not found while enumerating groups")
            group_ids = []
        manager.safe_point()

        bookmark = resume.group_id if resume is not None and project_index == 0 and resumed_project else None
        remaining_groups, _resumed = _slice_from_bookmark(group_ids, bookmark)
        next_project = (
            AirbrakeResumeConfig(project_id=remaining_projects[project_index + 1])
            if project_index + 1 < len(remaining_projects)
            else None
        )

        for group_index, group_id in enumerate(remaining_groups):
            if groups_fanned_out >= GROUP_STATS_MAX_GROUPS_PER_SYNC:
                logger.warning(
                    f"Airbrake: group stats budget ({GROUP_STATS_MAX_GROUPS_PER_SYNC}) reached, stopping group stats sync"
                )
                return
            groups_fanned_out += 1

            following = (
                AirbrakeResumeConfig(project_id=project_id, group_id=remaining_groups[group_index + 1])
                if group_index + 1 < len(remaining_groups)
                else next_project
            )
            try:
                yield from _stats_series_rows(
                    session,
                    api_key,
                    endpoint_config.path.format(project_id=project_id, group_id=group_id),
                    endpoint_config.stats,
                    windows,
                    {"projectId": project_id, "groupId": group_id},
                    logger,
                    manager,
                    current=AirbrakeResumeConfig(project_id=project_id, group_id=group_id),
                    following=following,
                )
            except requests.HTTPError as exc:
                if not _is_not_found(exc):
                    raise
                logger.warning(f"Airbrake: group {group_id} in project {project_id} not found, skipping stats")
                manager.safe_point()


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
    elif endpoint == "activities":
        yield from _project_fan_out_rows(session, api_key, endpoint_config, logger, resumable_source_manager)
    elif endpoint in ("project_stats", "group_stats"):
        stats_rows = _project_stats_rows if endpoint == "project_stats" else _group_stats_rows
        yield from stats_rows(
            session,
            api_key,
            endpoint_config,
            logger,
            resumable_source_manager,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )
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
