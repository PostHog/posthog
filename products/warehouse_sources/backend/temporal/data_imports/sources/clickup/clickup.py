import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import CLICKUP_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLICKUP_BASE_URL = "https://api.clickup.com/api/v2"

# Get Filtered Team Tasks is the only paginated endpoint; ClickUp caps it at 100 rows/page.
TASKS_PAGE_SIZE = 100

# ClickUp returns these task timestamps as epoch-milliseconds strings. We normalize them to
# ISO 8601 so they land as proper datetime columns and can drive partitioning / incremental sync.
TASK_DATE_FIELDS = ("date_created", "date_updated", "date_closed", "date_done", "start_date", "due_date")


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
            {"client": _client_config(api_key), "resources": [_flat_resource("workspaces", "/team", config.data_key)]},
            team_id,
            job_id,
            None,
        )
        items = lambda: resource
    elif config.kind == "team_scoped":
        path = f"/team/{workspace_id}/{config.resource_path}"
        resource = rest_api_resource(
            {"client": _client_config(api_key), "resources": [_flat_resource(endpoint, path, config.data_key)]},
            team_id,
            job_id,
            None,
        )
        items = lambda: resource
    elif config.kind == "space_children":
        resource = _space_children_resource(
            api_key, workspace_id, config.resource_path or "", config.data_key, team_id, job_id
        )
        items = lambda: resource
    elif config.kind == "lists":
        list_resources = _lists_resources(api_key, workspace_id, team_id, job_id)
        items = lambda: _chain_resources(list_resources)
    else:
        raise ValueError(f"Unknown ClickUp endpoint kind: {config.kind}")

    return SourceResponse(
        name=endpoint,
        items=items,
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
