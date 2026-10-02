import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import CLICKUP_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CLICKUP_BASE_URL = "https://api.clickup.com/api/v2"

# Get Filtered Team Tasks is the only paginated endpoint; ClickUp caps it at 100 rows/page.
TASKS_PAGE_SIZE = 100

# ClickUp returns these task timestamps as epoch-milliseconds strings. We normalize them to
# ISO 8601 so they land as proper datetime columns and can drive partitioning / incremental sync.
TASK_DATE_FIELDS = ("date_created", "date_updated", "date_closed", "date_done", "start_date", "due_date")

# Same epoch-millisecond treatment for a time entry's own timestamps.
TIME_ENTRY_DATE_FIELDS = ("start", "end", "at")

# The time entries endpoint is not paginated: one request returns the whole window, so the window
# has to stay small enough that a busy workspace's response is still a sane size.
TIME_ENTRIES_WINDOW_DAYS = 30
# Where a full refresh starts walking. The endpoint needs an explicit `start_date` (it otherwise
# answers with just the last 30 days), and ClickUp itself launched in 2017, so no tracked time can
# predate this.
TIME_ENTRIES_HISTORY_FLOOR = datetime(2017, 1, 1, tzinfo=UTC)

# Get Bulk Tasks' Time in Status accepts at most 100 task ids per request.
TIME_IN_STATUS_BATCH_SIZE = 100

# (connect, read) seconds. Left unset, a host that accepts the connection and then stalls holds
# an import worker open with no bound. The client raises a timeout as retryable, so a stall
# costs a few bounded attempts instead.
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)


@dataclasses.dataclass(frozen=True)
class ClickUpResumeConfig:
    # Zero-indexed page of the Get Filtered Team Tasks endpoint to resume from.
    page: int = 0
    # Epoch-millisecond start of the time entries window to resume from. None means "start from
    # the beginning of the range this sync covers".
    window_start: Optional[int] = None


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


def _normalize_time_entry(entry: dict[str, Any]) -> dict[str, Any]:
    for date_field in TIME_ENTRY_DATE_FIELDS:
        if date_field in entry:
            entry[date_field] = _ms_to_iso(entry[date_field])
    return entry


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


class ClickUpTaskPaginator(BasePaginator):
    """Page-number pagination for Get Filtered Team Tasks.

    ClickUp signals the final page in three ways, any of which stops the walk: an empty page, a
    ``last_page: true`` flag, or a short (< page size) page. It reports neither a total count nor a
    next-page link, so no built-in paginator fits.

    Resume checkpoints the page just yielded (not the next one): on a crash we re-fetch and re-yield
    it, and merge on the primary key dedupes the overlap.
    """

    def __init__(self, page: int = 0, page_size: int = TASKS_PAGE_SIZE) -> None:
        super().__init__()
        self.page = page
        self.page_size = page_size
        # The page most recently fetched — what resume must re-fetch. Distinct from self.page,
        # which update_state advances to point at the next page to request.
        self._current_page = page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._current_page = self.page

        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = {}

        if body.get("last_page") is True or len(data) < self.page_size:
            self._has_next_page = False
            return

        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self._current_page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._current_page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"ClickUpTaskPaginator(page={self.page})"


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": CLICKUP_BASE_URL,
        "headers": {"Accept": "application/json"},
        # Personal tokens (pk_...) and OAuth2 access tokens both go in the raw Authorization
        # header with no "Bearer" prefix. Framework auth redacts the value from logs.
        "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
        # Every endpoint except tasks returns its whole result in one un-paginated response.
        "paginator": SinglePagePaginator(),
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


def _flat_resource(name: str, path: str, data_key: str) -> EndpointResource:
    return {
        "name": name,
        "endpoint": {
            "path": path,
            "data_selector": data_key,
        },
    }


def _tasks_resource(
    api_key: str,
    workspace_id: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Resource:
    params: dict[str, Any] = {
        # Order by created (immutable) so pagination stays stable as tasks are updated mid-sync.
        "order_by": "created",
        # Closed tasks and subtasks are excluded by default — opt in so we capture everything.
        "include_closed": "true",
        "subtasks": "true",
    }
    if should_use_incremental_field:
        params["date_updated_gt"] = {
            "type": "incremental",
            "cursor_path": "date_updated",
            "convert": _to_epoch_ms,
        }

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": "tasks",
                "endpoint": {
                    "path": f"/team/{workspace_id}/task",
                    "params": params,
                    "data_selector": "tasks",
                    "paginator": ClickUpTaskPaginator(),
                },
                "data_map": _normalize_task,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ClickUpResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _space_children_resource(
    api_key: str, workspace_id: str, resource_path: str, data_key: str, team_id: int, job_id: str
) -> Resource:
    """Fan out over every space in the workspace and yield rows from a per-space resource."""
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            _flat_resource("spaces", f"/team/{workspace_id}/space", "spaces"),
            {
                "name": data_key,
                "endpoint": {
                    "path": f"/space/{{space_id}}/{resource_path}",
                    "params": {"space_id": {"type": "resolve", "resource": "spaces", "field": "id"}},
                    "data_selector": data_key,
                },
            },
        ],
    }
    resources = {r.name: r for r in rest_api_resources(config, team_id, job_id, None)}
    return resources[data_key]


def _lists_resources(api_key: str, workspace_id: str, team_id: int, job_id: str) -> list[Resource]:
    """Lists live in two places: directly under a space (folderless) and under folders."""
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            _flat_resource("spaces", f"/team/{workspace_id}/space", "spaces"),
            {
                "name": "folderless_lists",
                "endpoint": {
                    "path": "/space/{space_id}/list",
                    "params": {"space_id": {"type": "resolve", "resource": "spaces", "field": "id"}},
                    "data_selector": "lists",
                },
            },
            {
                "name": "folders",
                "endpoint": {
                    "path": "/space/{space_id}/folder",
                    "params": {"space_id": {"type": "resolve", "resource": "spaces", "field": "id"}},
                    "data_selector": "folders",
                },
            },
            {
                "name": "folder_lists",
                "endpoint": {
                    "path": "/folder/{folder_id}/list",
                    "params": {"folder_id": {"type": "resolve", "resource": "folders", "field": "id"}},
                    "data_selector": "lists",
                },
            },
        ],
    }
    resources = {r.name: r for r in rest_api_resources(config, team_id, job_id, None)}
    return [resources["folderless_lists"], resources["folder_lists"]]


def _chain_resources(resources: list[Resource]) -> Iterator[list[dict[str, Any]]]:
    for resource in resources:
        yield from resource


def _make_client(api_key: str) -> RESTClient:
    """Client for the endpoints whose fan-out or windowing the declarative config can't express."""
    return RESTClient(
        base_url=CLICKUP_BASE_URL,
        headers={"Accept": "application/json"},
        auth=APIKeyAuth(api_key=api_key, name="Authorization", location="header"),
        request_timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _member_user_ids(client: RESTClient, workspace_id: str) -> list[str]:
    """User ids of every member of the configured workspace.

    Without `assignee`, the time entries endpoint answers with only the calling user's entries, so
    a workspace-wide table has to name the members. Passing `assignee` needs an owner/admin token;
    a token without it gets a 403, which `get_non_retryable_errors` reports as a permission problem
    rather than retrying.

    Raises when the workspace resolves no members. A workspace always holds at least the calling
    user, so an empty list means the token lost access or the response shape changed. Carrying on
    without `assignee` would quietly fill the table with one user's time.
    """
    user_ids: list[str] = []
    for page in client.paginate(path="/team", paginator=SinglePagePaginator(), data_selector="teams"):
        for team in page:
            if str(team.get("id")) != str(workspace_id):
                continue
            for member in team.get("members") or []:
                user = member.get("user") if isinstance(member.get("user"), dict) else member
                user_id = user.get("id")
                if user_id is not None:
                    user_ids.append(str(user_id))

    if not user_ids:
        raise ValueError(
            f"ClickUp returned no members for workspace {workspace_id}. "
            "Check that the API token still has access to the workspace, then sync again."
        )
    return user_ids


def _epoch_ms(value: datetime) -> int:
    return round(value.timestamp() * 1000)


def _time_entries_range_start(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> datetime:
    if should_use_incremental_field:
        millis = _to_epoch_ms(db_incremental_field_last_value)
        if millis is not None:
            return datetime.fromtimestamp(millis / 1000, tz=UTC)
    return TIME_ENTRIES_HISTORY_FLOOR


def _time_entry_windows(start: datetime, end: datetime) -> Iterator[SyncWindow[int]]:
    """Split [start, end] into fixed-length windows, oldest first.

    Consecutive windows share a boundary millisecond, so an entry starting exactly on one is
    fetched twice; merge on the primary key dedupes it.
    """
    cursor = start
    step = timedelta(days=TIME_ENTRIES_WINDOW_DAYS)
    while cursor < end:
        window_end = min(cursor + step, end)
        yield SyncWindow(start=_epoch_ms(cursor), end=_epoch_ms(window_end))
        cursor = window_end


def _time_entries_rows(
    api_key: str,
    workspace_id: str,
    resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    client = _make_client(api_key)

    params: dict[str, Any] = {
        "include_task_tags": "true",
        "include_location_names": "true",
        "assignee": ",".join(_member_user_ids(client, workspace_id)),
    }

    start = _time_entries_range_start(should_use_incremental_field, db_incremental_field_last_value)
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.window_start is not None:
            start = datetime.fromtimestamp(resume.window_start / 1000, tz=UTC)

    for window in _time_entry_windows(start, datetime.now(tz=UTC)):
        for rows in client.paginate(
            path=f"/team/{workspace_id}/time_entries",
            params={**params, "start_date": window.start, "end_date": window.end},
            paginator=SinglePagePaginator(),
            data_selector="data",
        ):
            if rows:
                yield [_normalize_time_entry(row) for row in rows]
        # Checkpoint the window just yielded, not the next one: a crash re-fetches it (merge
        # dedupes) rather than skipping it.
        resumable_source_manager.save_state(ClickUpResumeConfig(window_start=window.start))


def _all_task_ids(api_key: str, workspace_id: str, team_id: int, job_id: str) -> Iterator[str]:
    """Every task id in the workspace, for the fan-outs keyed on tasks.

    Deliberately unfiltered by `date_updated_gt`: time in status is a full-refresh table with no
    timestamp of its own, so bounding the walk would leave older tasks' rows permanently stale.
    """
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": "tasks",
                "endpoint": {
                    "path": f"/team/{workspace_id}/task",
                    "params": {"order_by": "created", "include_closed": "true", "subtasks": "true"},
                    "data_selector": "tasks",
                    "paginator": ClickUpTaskPaginator(),
                },
            }
        ],
    }
    for page in rest_api_resource(config, team_id, job_id, None):
        for task in page:
            task_id = task.get("id")
            if task_id is not None:
                yield str(task_id)


def _time_in_status_rows(client: RESTClient, task_ids: list[str]) -> list[dict[str, Any]]:
    """One row per task from the bulk time-in-status endpoint.

    It answers with a map of task id -> {current_status, status_history} instead of a wrapped
    array, so there is no data selector to point at. The whole body arrives as a single item and is
    flattened here into rows carrying the task id the merge key needs.
    """
    rows: list[dict[str, Any]] = []
    for page in client.paginate(
        path="/task/bulk_time_in_status/task_ids",
        # `requests` encodes a list as one repeated param per element, which is the format the
        # endpoint documents (task_ids=3cuh&task_ids=g4fs).
        params={"task_ids": task_ids},
        paginator=SinglePagePaginator(),
    ):
        for body in page:
            if not isinstance(body, dict):
                continue
            for task_id, time_in_status in body.items():
                if isinstance(time_in_status, dict):
                    rows.append({"task_id": task_id, **time_in_status})
    return rows


def _task_time_in_status_rows(
    api_key: str, workspace_id: str, team_id: int, job_id: str
) -> Iterator[list[dict[str, Any]]]:
    client = _make_client(api_key)
    batch: list[str] = []
    for task_id in _all_task_ids(api_key, workspace_id, team_id, job_id):
        batch.append(task_id)
        if len(batch) == TIME_IN_STATUS_BATCH_SIZE:
            yield _time_in_status_rows(client, batch)
            batch = []
    if batch:
        yield _time_in_status_rows(client, batch)


def _list_children_rows(
    api_key: str, workspace_id: str, resource_path: str, data_key: str, team_id: int, job_id: str
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every list in the workspace and yield rows from a per-list resource.

    Three levels deep (space -> folder -> list -> resource), which the declarative fan-out doesn't
    cover, and the rows carry no list id of their own, so each is stamped with the list it came
    from for the composite primary key.
    """
    client = _make_client(api_key)
    # An archived or just-deleted list stops serving its sub-resources; skip it rather than fail
    # the whole table.
    hooks = create_response_hooks([{"status_code": 404, "action": "ignore"}], resource_name=data_key)

    for page in _chain_resources(_lists_resources(api_key, workspace_id, team_id, job_id)):
        for list_row in page:
            list_id = list_row.get("id")
            if list_id is None:
                continue
            for rows in client.paginate(
                path=f"/list/{list_id}/{resource_path}",
                paginator=SinglePagePaginator(),
                data_selector=data_key,
                hooks=hooks,
            ):
                if rows:
                    yield [{**row, "_list_id": str(list_id)} for row in rows]


def clickup_source(
    api_key: str,
    workspace_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CLICKUP_ENDPOINTS[endpoint]

    items: Any
    if config.kind == "tasks":
        resource = _tasks_resource(
            api_key,
            workspace_id,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        items = lambda: resource
    elif config.kind == "workspaces":
        resource = rest_api_resource(
            {
                "client": _client_config(api_key),
                "resources": [_flat_resource("workspaces", "/team", config.data_key or "")],
            },
            team_id,
            job_id,
            None,
        )
        items = lambda: resource
    elif config.kind == "team_scoped":
        path = f"/team/{workspace_id}/{config.resource_path}"
        resource = rest_api_resource(
            {"client": _client_config(api_key), "resources": [_flat_resource(endpoint, path, config.data_key or "")]},
            team_id,
            job_id,
            None,
        )
        items = lambda: resource
    elif config.kind == "space_children":
        resource = _space_children_resource(
            api_key, workspace_id, config.resource_path or "", config.data_key or "", team_id, job_id
        )
        items = lambda: resource
    elif config.kind == "lists":
        list_resources = _lists_resources(api_key, workspace_id, team_id, job_id)
        items = lambda: _chain_resources(list_resources)
    elif config.kind == "list_children":
        items = lambda: _list_children_rows(
            api_key, workspace_id, config.resource_path or "", config.data_key or "", team_id, job_id
        )
    elif config.kind == "time_entries":
        items = lambda: _time_entries_rows(
            api_key,
            workspace_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.kind == "task_time_in_status":
        items = lambda: _task_time_in_status_rows(api_key, workspace_id, team_id, job_id)
    else:
        raise ValueError(f"Unknown ClickUp endpoint kind: {config.kind}")

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # Tasks are fetched newest-first (default ClickUp order). Time entries arrive in whatever
        # order the endpoint chooses within a window, because it documents no sort and takes no
        # sort param. With sort_mode="desc" the pipeline only commits the cursor watermark once a sync
        # fully completes, so a mid-sync crash never advances the cursor past unfetched rows. The
        # server filters (`date_updated_gt`, `start_date`/`end_date`), not row ordering, are what
        # bound each incremental fetch. Live ordering semantics were not verified against the API
        # as no test credentials were available.
        sort_mode="desc" if config.kind in ("tasks", "time_entries") else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, workspace_id: str | None) -> tuple[bool, str | None]:
    """Confirm the token is genuine and (when provided) can see the configured workspace."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{CLICKUP_BASE_URL}/team", headers=_get_headers(api_key), timeout=10
        )
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
