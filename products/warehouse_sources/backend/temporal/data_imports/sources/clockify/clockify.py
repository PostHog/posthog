import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import CLOCKIFY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# Global host. Clockify also serves regional hosts (euc1/use2/euw2/apse2); the global host
# resolves to the user's region, so a single base URL works for every key.
CLOCKIFY_BASE_URL = "https://api.clockify.me/api/v1"

# Single-level fan-out endpoints: one GET per workspace. Two-level ones (tasks, time_entries)
# chain a second parent (projects/users) and are handled explicitly below.
_WORKSPACE_CHILD_ENDPOINTS = ("users", "clients", "projects", "tags")


class ClockifyPageNumberPaginator(PageNumberPaginator):
    """Page/`page-size` pagination over Clockify's bare JSON arrays.

    Clockify exposes no total count, so — like the hand-rolled loop this replaces — a page shorter
    than the requested size (or an empty page) is the last page. Stopping on a short page avoids the
    extra empty-page request the plain ``PageNumberPaginator`` would pay.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


@dataclasses.dataclass
class ClockifyResumeConfig:
    # Opaque paginator/fan-out state handed back by the rest_source framework (paginator page for
    # workspaces, per-parent completed-path progress for single-level fan-out). Retained as a single
    # blob so the shape can evolve without a state-format migration.
    fanout_state: dict[str, Any] | None = None
    # Legacy fields from the hand-rolled resume format. Kept (with defaults) so an old saved state
    # still parses via ``dataclass(**saved)``; a run resumed from one starts fan-out fresh (a re-read
    # the merge dedupes) rather than mis-mapping the old positional scope onto the new state.
    workspace_id: str | None = None
    parent_id: str | None = None
    page: int = 1


def _headers() -> dict[str, str]:
    # Auth (the X-Api-Key header) is supplied via the framework auth config so its value is redacted
    # from logs; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


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


def _flatten_time_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Surface the nested `timeInterval` object as top-level columns so the interval start can be
    used as the incremental cursor and partition key."""
    interval = item.get("timeInterval")
    if isinstance(interval, dict):
        item["time_interval_start"] = interval.get("start")
        item["time_interval_end"] = interval.get("end")
        item["time_interval_duration"] = interval.get("duration")
    return item


# Fan-out injects the parent id under the framework's ``_<parent>_<field>`` naming; rename it back to
# the flat ``workspace_id`` / ``project_id`` / ``user_id`` columns the tables have always exposed.
_rename_workspace = rename_parent_fields("workspaces", {"id": "workspace_id"})
_rename_task_parents = rename_parent_fields("projects", {"workspace_id": "workspace_id", "id": "project_id"})
_rename_time_entry_parents = rename_parent_fields("users", {"workspace_id": "workspace_id", "id": "user_id"})


def _time_entry_map(row: dict[str, Any]) -> dict[str, Any]:
    return _rename_time_entry_parents(_flatten_time_entry(row))


def _incremental_config(
    should_use_incremental_field: bool, db_incremental_field_last_value: Any
) -> IncrementalConfig | None:
    """Server-side `start` filter for time_entries, only when we have a cursor to filter on.

    Mirrors the old behaviour: no filter on a first (full) sync, and the persisted watermark is
    clamped to now and formatted the way Clockify's `start` expects.
    """
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return None
    return {
        "start_param": "start",
        "cursor_path": "time_interval_start",
        "convert": lambda value: _format_datetime_z(_clamp_future_value_to_now(value)),
    }


def _workspaces_resource() -> EndpointResource:
    config = CLOCKIFY_ENDPOINTS["workspaces"]
    return {
        "name": "workspaces",
        "endpoint": {
            "path": config.path,
            "params": {"page-size": config.page_size},
            "paginator": ClockifyPageNumberPaginator(config.page_size),
            "data_selector_required": True,
        },
    }


def _workspace_child_resource(endpoint: str) -> EndpointResource:
    config = CLOCKIFY_ENDPOINTS[endpoint]
    return {
        "name": endpoint,
        "include_from_parent": ["id"],
        "endpoint": {
            "path": config.path,
            "params": {
                "workspace_id": {"type": "resolve", "resource": "workspaces", "field": "id"},
                "page-size": config.page_size,
            },
            "paginator": ClockifyPageNumberPaginator(config.page_size),
            "data_selector_required": True,
        },
        "data_map": _rename_workspace,
    }


def _tasks_resource() -> EndpointResource:
    config = CLOCKIFY_ENDPOINTS["tasks"]
    return {
        "name": "tasks",
        "include_from_parent": ["workspace_id", "id"],
        "endpoint": {
            "path": config.path,
            "params": {
                "workspace_id": {"type": "resolve", "resource": "projects", "field": "workspace_id"},
                "project_id": {"type": "resolve", "resource": "projects", "field": "id"},
                "page-size": config.page_size,
            },
            "paginator": ClockifyPageNumberPaginator(config.page_size),
            "data_selector_required": True,
        },
        "data_map": _rename_task_parents,
    }


def _time_entries_resource(incremental: IncrementalConfig | None) -> EndpointResource:
    config = CLOCKIFY_ENDPOINTS["time_entries"]
    endpoint: dict[str, Any] = {
        "path": config.path,
        "params": {
            "workspace_id": {"type": "resolve", "resource": "users", "field": "workspace_id"},
            "user_id": {"type": "resolve", "resource": "users", "field": "id"},
            "page-size": config.page_size,
        },
        "paginator": ClockifyPageNumberPaginator(config.page_size),
        "data_selector_required": True,
    }
    if incremental is not None:
        endpoint["incremental"] = incremental
    return {
        "name": "time_entries",
        "include_from_parent": ["workspace_id", "id"],
        "endpoint": endpoint,
        "data_map": _time_entry_map,
    }


def _resources_for(endpoint: str, incremental: IncrementalConfig | None) -> list[EndpointResource]:
    if endpoint == "workspaces":
        return [_workspaces_resource()]
    if endpoint in _WORKSPACE_CHILD_ENDPOINTS:
        return [_workspaces_resource(), _workspace_child_resource(endpoint)]
    if endpoint == "tasks":
        return [_workspaces_resource(), _workspace_child_resource("projects"), _tasks_resource()]
    if endpoint == "time_entries":
        return [_workspaces_resource(), _workspace_child_resource("users"), _time_entries_resource(incremental)]
    raise ValueError(f"Unknown Clockify endpoint: {endpoint}")


def _build_rest_config(
    api_key: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> RESTAPIConfig:
    incremental = _incremental_config(should_use_incremental_field, db_incremental_field_last_value)
    return {
        "client": {
            "base_url": CLOCKIFY_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
        },
        "resource_defaults": {},
        "resources": _resources_for(endpoint, incremental),
    }


def clockify_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClockifyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CLOCKIFY_ENDPOINTS[endpoint]
    rest_config = _build_rest_config(api_key, endpoint, should_use_incremental_field, db_incremental_field_last_value)

    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes) rather
        # than skipping it. A ``None`` state means no page remains — nothing to persist. Never fires
        # for the two-level fan-outs (tasks/time_entries), where the framework disables resume.
        if state is not None:
            resumable_source_manager.save_state(ClockifyResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource: Resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    """A Clockify API key is user-scoped (no per-endpoint scopes), so one cheap `/user` probe
    confirms the key is genuine for everything it can reach."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CLOCKIFY_BASE_URL}/user",
        headers={"X-Api-Key": api_key, **_headers()},
    )
    return ok
