import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import (
    CLOCKIFY_ENDPOINTS,
    ClockifyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Global host. Clockify also serves regional hosts (euc1/use2/euw2/apse2); the global host
# resolves to the user's region, so a single base URL works for every key.
CLOCKIFY_BASE_URL = "https://api.clockify.me/api/v1"


class ClockifyRetryableError(Exception):
    pass


@dataclasses.dataclass
class ClockifyResumeConfig:
    # The fan-out scope (workspace + optional parent project/user) and the 1-based page we were
    # reading when the last batch was yielded. Stable ids, not positional indexes, so scopes
    # added/removed between a crash and the retry can't resume us into the wrong place.
    workspace_id: str | None = None
    parent_id: str | None = None
    page: int = 1


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _format_datetime_z(value: Any) -> str:
    """Format a datetime/date as `yyyy-MM-ddThh:mm:ssZ`, the format Clockify's `start` filter wants."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        # Already a string (e.g. an ISO timestamp persisted as the cursor) — pass through.
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime cursor at now.

    A future-dated `start` filter would silently match nothing and stall the incremental sync.
    Asking for entries newer than now is a no-op anyway, so capping keeps the sync self-healing.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    if isinstance(value, str):
        # The cursor can reach us as an ISO string depending on how it was persisted/deserialised.
        # Parse it so a future-dated string is clamped too; a non-ISO string passes through.
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return now if aware > now else value
    return value


def validate_credentials(api_key: str) -> bool:
    """A Clockify API key is user-scoped (no per-endpoint scopes), so one cheap `/user` probe
    confirms the key is genuine for everything it can reach."""
    try:
        response = make_tracked_session().get(f"{CLOCKIFY_BASE_URL}/user", headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((ClockifyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Fetch one page. Clockify list endpoints return a bare JSON array.

    429s (rate limited; Clockify sends no reset header, so we back off) and 5xx are retried;
    a non-list body or 4xx auth error is surfaced via `raise_for_status()`.
    """
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise ClockifyRetryableError(f"Clockify API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Clockify API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, list):
        # Every list endpoint we hit returns an array; a dict here is an unexpected error shape.
        logger.error(f"Clockify API returned a non-list body: url={url}, body={response.text}")
        return []
    return data


def _flatten_time_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Surface the nested `timeInterval` object as top-level columns so the interval start can be
    used as the incremental cursor and partition key."""
    interval = item.get("timeInterval")
    if isinstance(interval, dict):
        item["time_interval_start"] = interval.get("start")
        item["time_interval_end"] = interval.get("end")
        item["time_interval_duration"] = interval.get("duration")
    return item


def _get_item_mapper(endpoint: str) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if endpoint == "time_entries":
        return _flatten_time_entry
    return None


def _list_ids(
    session: requests.Session, headers: dict[str, str], base_path: str, page_size: int, logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through a workspace-scoped list endpoint, yielding each row's id. Used to enumerate
    the parents (projects/users) a two-level fan-out walks over."""
    page = 1
    while True:
        data = _fetch_page(session, _build_url(base_path, {"page": page, "page-size": page_size}), headers, logger)
        if not data:
            break
        for item in data:
            yield item["id"]
        if len(data) < page_size:
            break
        page += 1


def _list_workspace_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    data = _fetch_page(session, f"{CLOCKIFY_BASE_URL}/workspaces", headers, logger)
    return [workspace["id"] for workspace in data]


def _build_scopes(
    session: requests.Session,
    headers: dict[str, str],
    config: ClockifyEndpointConfig,
    logger: FilteringBoundLogger,
) -> list[tuple[str, str | None, str]]:
    """Materialize the (workspace_id, parent_id, full_url) tuples this endpoint iterates.

    Built up front so resume can match the saved scope by id. For single-level fan-out
    parent_id is None; for two-level fan-out we enumerate the parent endpoint per workspace.
    """
    scopes: list[tuple[str, str | None, str]] = []
    for workspace_id in _list_workspace_ids(session, headers, logger):
        if config.fan_out_parent is None:
            scopes.append((workspace_id, None, CLOCKIFY_BASE_URL + config.path.format(workspace_id=workspace_id)))
            continue

        assert config.parent_id_placeholder is not None  # set whenever fan_out_parent is
        parent_config = CLOCKIFY_ENDPOINTS[config.fan_out_parent]
        parent_path = CLOCKIFY_BASE_URL + parent_config.path.format(workspace_id=workspace_id)
        for parent_id in _list_ids(session, headers, parent_path, parent_config.page_size, logger):
            url = CLOCKIFY_BASE_URL + config.path.format(
                **{"workspace_id": workspace_id, config.parent_id_placeholder: parent_id}
            )
            scopes.append((workspace_id, parent_id, url))
    return scopes


def _find_scope_index(
    scopes: list[tuple[str, str | None, str]], workspace_id: str | None, parent_id: str | None
) -> int | None:
    for index, (scope_workspace_id, scope_parent_id, _url) in enumerate(scopes):
        if scope_workspace_id == workspace_id and scope_parent_id == parent_id:
            return index
    return None


def _paginate_scope(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    config: ClockifyEndpointConfig,
    batcher: Batcher,
    manager: ResumableSourceManager[ClockifyResumeConfig],
    logger: FilteringBoundLogger,
    mapper: Callable[[dict[str, Any]], dict[str, Any]] | None,
    workspace_id: str | None,
    parent_id: str | None,
    start_page: int,
    inject: dict[str, str],
    extra_params: dict[str, Any],
) -> Iterator[Any]:
    """Page through one scope, batching rows. Saves resume state AFTER yielding each batch so a
    crash re-reads the current page (merge dedupes on the primary key) rather than skipping it."""
    page = start_page
    while True:
        params: dict[str, Any] = {"page": page, "page-size": config.page_size, **extra_params}
        data = _fetch_page(session, _build_url(base_url, params), headers, logger)
        if not data:
            break

        for item in data:
            row = mapper(item) if mapper else item
            row.update(inject)
            batcher.batch(row)
            if batcher.should_yield():
                yield batcher.get_table()
                manager.save_state(ClockifyResumeConfig(workspace_id=workspace_id, parent_id=parent_id, page=page))

        # A short page (fewer rows than asked for) is the last page.
        if len(data) < config.page_size:
            break
        page += 1


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClockifyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = CLOCKIFY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    session = make_tracked_session()
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    mapper = _get_item_mapper(endpoint)

    # Workspaces is the one non-fan-out endpoint.
    if not config.workspace_scoped:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        start_page = resume.page if resume is not None else 1
        yield from _paginate_scope(
            session,
            headers,
            CLOCKIFY_BASE_URL + config.path,
            config,
            batcher,
            resumable_source_manager,
            logger,
            mapper,
            workspace_id=None,
            parent_id=None,
            start_page=start_page,
            inject={},
            extra_params={},
        )
        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
        return

    # Server-side incremental filter (time_entries only). `incremental_field` is the user's chosen
    # cursor; we only have a filter param when the endpoint declares one.
    extra_params: dict[str, Any] = {}
    if should_use_incremental_field and db_incremental_field_last_value and config.incremental_param:
        cursor_value = _clamp_future_value_to_now(db_incremental_field_last_value)
        extra_params[config.incremental_param] = _format_datetime_z(cursor_value)

    scopes = _build_scopes(session, headers, config, logger)

    # Resolve resume to a starting scope + page. If the bookmarked scope no longer exists, start
    # from the beginning — merge dedupes the re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = 0
    resume_page = 1
    if resume is not None:
        matched = _find_scope_index(scopes, resume.workspace_id, resume.parent_id)
        if matched is not None:
            start_index = matched
            resume_page = resume.page
            logger.debug(f"Clockify: resuming {endpoint} from scope index {matched}, page {resume_page}")

    for index in range(start_index, len(scopes)):
        workspace_id, parent_id, url = scopes[index]
        inject: dict[str, str] = {"workspace_id": workspace_id}
        if parent_id is not None and config.parent_id_placeholder is not None:
            inject[config.parent_id_placeholder] = parent_id
        yield from _paginate_scope(
            session,
            headers,
            url,
            config,
            batcher,
            resumable_source_manager,
            logger,
            mapper,
            workspace_id=workspace_id,
            parent_id=parent_id,
            start_page=resume_page if index == start_index else 1,
            inject=inject,
            extra_params=extra_params,
        )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def clockify_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClockifyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = CLOCKIFY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
