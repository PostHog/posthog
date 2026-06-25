import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import CLICKUP_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLICKUP_BASE_URL = "https://api.clickup.com/api/v2"

# Get Filtered Team Tasks is the only paginated endpoint; ClickUp caps it at 100 rows/page.
TASKS_PAGE_SIZE = 100
# Hard caps to bound fan-out scans; ClickUp workspaces rarely approach these.
MAX_SPACES = 1000
MAX_FOLDERS_PER_SPACE = 1000

# ClickUp returns these task timestamps as epoch-milliseconds strings. We normalize them to
# ISO 8601 so they land as proper datetime columns and can drive partitioning / incremental sync.
TASK_DATE_FIELDS = ("date_created", "date_updated", "date_closed", "date_done", "start_date", "due_date")


class ClickUpRetryableError(Exception):
    pass


@dataclasses.dataclass
class ClickUpResumeConfig:
    # Zero-indexed page of the Get Filtered Team Tasks endpoint to resume from.
    page: int


def _get_headers(api_key: str) -> dict[str, str]:
    # ClickUp accepts both personal tokens (pk_...) and OAuth2 access tokens in the raw
    # Authorization header (no "Bearer" prefix).
    return {"Authorization": api_key, "Accept": "application/json"}


def _ms_to_iso(value: Any) -> Any:
    """Convert a ClickUp epoch-millisecond timestamp to an ISO 8601 UTC string.

    Returns the original value untouched when it isn't a usable epoch (None, empty, or
    non-numeric) so we never fabricate timestamps.
    """
    if value is None or value == "":
        return value
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return value
    # Build from an exact millisecond timedelta — `fromtimestamp(millis / 1000)` loses
    # precision in the float division and can land a millisecond off.
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=millis)).isoformat()


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    for date_field in TASK_DATE_FIELDS:
        if date_field in task:
            task[date_field] = _ms_to_iso(task[date_field])
    return task


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Convert an incremental cursor value (datetime/date/epoch) to epoch milliseconds for
    ClickUp's date_updated_gt filter."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return round(dt.timestamp() * 1000)
    if isinstance(value, date):
        return round(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{CLICKUP_BASE_URL}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def validate_credentials(api_key: str, workspace_id: str | None) -> tuple[bool, str | None]:
    """Confirm the token is genuine and (when provided) can see the configured workspace."""
    try:
        response = make_tracked_session().get(f"{CLICKUP_BASE_URL}/team", headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 401:
        return False, "Invalid ClickUp API token"
    if not response.ok:
        return False, f"ClickUp API error: {response.status_code} {response.text}"

    if workspace_id:
        teams = response.json().get("teams", [])
        if not any(str(team.get("id")) == str(workspace_id) for team in teams):
            return False, f"Workspace '{workspace_id}' is not accessible with this token"

    return True, None


@retry(
    retry=retry_if_exception_type((ClickUpRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict[str, Any]:
    response = make_tracked_session().get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise ClickUpRetryableError(f"ClickUp API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"ClickUp API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _list_space_ids(workspace_id: str, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    spaces = _fetch(_build_url(f"/team/{workspace_id}/space"), headers, logger).get("spaces", [])
    if len(spaces) >= MAX_SPACES:
        logger.warning(f"ClickUp: hit space cap ({MAX_SPACES}) for workspace {workspace_id}; some spaces skipped")
    return [str(space["id"]) for space in spaces[:MAX_SPACES]]


def _iter_tasks(
    workspace_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    base_params: dict[str, Any] = {
        # Order by created (immutable) so pagination stays stable as tasks are updated mid-sync.
        "order_by": "created",
        # Closed tasks and subtasks are excluded by default — opt in so we capture everything.
        "include_closed": "true",
        "subtasks": "true",
    }
    if should_use_incremental_field:
        cutoff_ms = _to_epoch_ms(db_incremental_field_last_value)
        if cutoff_ms is not None:
            base_params["date_updated_gt"] = cutoff_ms

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 0
    if resume is not None:
        logger.debug(f"ClickUp: resuming tasks from page {page}")

    while True:
        data = _fetch(_build_url(f"/team/{workspace_id}/task", {**base_params, "page": page}), headers, logger)
        tasks = data.get("tasks", [])
        if not tasks:
            break

        yield [_normalize_task(task) for task in tasks]
        # Checkpoint the page we just yielded (not the next one): on a crash we re-fetch and
        # re-yield it, and merge on the primary key dedupes the overlap.
        resumable_source_manager.save_state(ClickUpResumeConfig(page=page))

        # ClickUp signals the final page either via `last_page` or a short (< page size) page.
        if data.get("last_page") is True or len(tasks) < TASKS_PAGE_SIZE:
            break
        page += 1


def _iter_space_children(
    workspace_id: str, resource_path: str, data_key: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every space in the workspace and yield rows from a per-space resource."""
    for space_id in _list_space_ids(workspace_id, headers, logger):
        data = _fetch(_build_url(f"/space/{space_id}/{resource_path}"), headers, logger)
        rows = data.get(data_key, [])
        if rows:
            yield rows


def _iter_lists(
    workspace_id: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    """Lists live in two places: directly under a space (folderless) and under folders."""
    for space_id in _list_space_ids(workspace_id, headers, logger):
        folderless = _fetch(_build_url(f"/space/{space_id}/list"), headers, logger).get("lists", [])
        if folderless:
            yield folderless

        folders = _fetch(_build_url(f"/space/{space_id}/folder"), headers, logger).get("folders", [])
        if len(folders) >= MAX_FOLDERS_PER_SPACE:
            logger.warning(f"ClickUp: hit folder cap ({MAX_FOLDERS_PER_SPACE}) for space {space_id}; some skipped")
        for folder in folders[:MAX_FOLDERS_PER_SPACE]:
            folder_lists = _fetch(_build_url(f"/folder/{folder['id']}/list"), headers, logger).get("lists", [])
            if folder_lists:
                yield folder_lists


def get_rows(
    api_key: str,
    workspace_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CLICKUP_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    if config.kind == "tasks":
        yield from _iter_tasks(
            workspace_id,
            headers,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.kind == "workspaces":
        rows = _fetch(_build_url("/team"), headers, logger).get(config.data_key, [])
        if rows:
            yield rows
    elif config.kind == "team_scoped":
        path = f"/team/{workspace_id}/{config.resource_path}"
        rows = _fetch(_build_url(path), headers, logger).get(config.data_key, [])
        if rows:
            yield rows
    elif config.kind == "space_children":
        yield from _iter_space_children(workspace_id, config.resource_path or "", config.data_key, headers, logger)
    elif config.kind == "lists":
        yield from _iter_lists(workspace_id, headers, logger)
    else:
        raise ValueError(f"Unknown ClickUp endpoint kind: {config.kind}")


def clickup_source(
    api_key: str,
    workspace_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CLICKUP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            workspace_id=workspace_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Tasks are fetched newest-first (default ClickUp order). With sort_mode="desc" the
        # pipeline only commits the cursor watermark once a sync fully completes, so a mid-sync
        # crash never advances the cursor past unfetched rows. The `date_updated_gt` server
        # filter (not row ordering) is what bounds each incremental fetch. Live ordering
        # semantics were not verified against the API as no test credentials were available.
        sort_mode="desc" if config.kind == "tasks" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
