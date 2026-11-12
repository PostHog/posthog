from dataclasses import field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

TOGGL_BASE_URL = "https://api.track.toggl.com"
API_V9_PREFIX = "/api/v9"
REPORTS_TIME_ENTRIES_PATH = "/reports/api/v3/workspace/{workspace_id}/search/time_entries"

# Projects document a cap of 200 per page. Tasks and tags document no cap, so their paginators do
# not rely on a short page to stop.
PAGE_SIZE = 200
# The Reports API documents 50 rows per page and no maximum. A page size it rejects would fail every
# sync, so this stays at the documented value.
REPORTS_PAGE_SIZE = 50
# The Reports API documents no maximum date range. Windows of at most one year keep each search in
# the range that earlier Reports API versions accepted.
REPORTS_WINDOW_DAYS = 365

Pagination = Literal["single", "page_short_stop", "page_total_count", "page_empty_stop"]


@frozen
class TogglEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    pagination: Pagination = "single"
    data_selector: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # A stable creation-time field. Never a last-updated field: those move rows between partitions.
    partition_key: Optional[str] = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    # Toggl answers 403 when the token's user cannot read this resource in one workspace (for
    # example a member, not an admin). Such a workspace is skipped instead of failing the sync.
    skip_forbidden_workspaces: bool = False


_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "at",
        "type": IncrementalFieldType.DateTime,
        "field": "at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

TOGGL_ENDPOINTS: dict[str, TogglEndpointConfig] = {
    "workspaces": TogglEndpointConfig(
        name="workspaces",
        path=f"{API_V9_PREFIX}/me/workspaces",
        primary_keys=["id"],
    ),
    "projects": TogglEndpointConfig(
        name="projects",
        path=f"{API_V9_PREFIX}/workspaces/{{workspace_id}}/projects",
        primary_keys=["workspace_id", "id"],
        pagination="page_short_stop",
        incremental_fields=_AT_INCREMENTAL_FIELDS,
        partition_key="created_at",
        extra_params={"active": "both"},
    ),
    "clients": TogglEndpointConfig(
        name="clients",
        path=f"{API_V9_PREFIX}/workspaces/{{workspace_id}}/clients",
        primary_keys=["workspace_id", "id"],
        extra_params={"status": "both"},
    ),
    "tags": TogglEndpointConfig(
        name="tags",
        path=f"{API_V9_PREFIX}/workspaces/{{workspace_id}}/tags",
        primary_keys=["workspace_id", "id"],
        pagination="page_empty_stop",
    ),
    "tasks": TogglEndpointConfig(
        name="tasks",
        path=f"{API_V9_PREFIX}/workspaces/{{workspace_id}}/tasks",
        primary_keys=["workspace_id", "id"],
        pagination="page_total_count",
        data_selector="data",
        incremental_fields=_AT_INCREMENTAL_FIELDS,
        # A creation-time sort keeps pages stable while tasks are renamed during a sync.
        extra_params={"active": "both", "sort_field": "created_at", "sort_order": "ASC"},
    ),
    "workspace_users": TogglEndpointConfig(
        name="workspace_users",
        path=f"{API_V9_PREFIX}/workspaces/{{workspace_id}}/users",
        primary_keys=["workspace_id", "id"],
        skip_forbidden_workspaces=True,
    ),
    "time_entries": TogglEndpointConfig(
        name="time_entries",
        path=REPORTS_TIME_ENTRIES_PATH,
        primary_keys=["workspace_id", "id"],
        incremental_fields=[
            {
                "label": "start",
                "type": IncrementalFieldType.DateTime,
                "field": "start",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(TOGGL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TOGGL_ENDPOINTS.items() if config.incremental_fields
}
