from dataclasses import field
from typing import Any, Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class ClockifyEndpointConfig:
    name: str
    # Path template relative to the API base. Placeholders are filled per fan-out scope:
    # {workspace_id} for every workspace-scoped endpoint, plus {project_id}/{user_id} for the
    # two-level fan-out endpoints (tasks/time_entries).
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable creation-style field used to partition the Delta table. Never an `updated_at`
    # style field — those rewrite partitions on every sync.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    # Clockify's max page-size is 5000; 1000 keeps each page well under the response/memory
    # ceiling while minimizing request count.
    page_size: int = 1000
    should_sync_default: bool = True
    # False only for `/workspaces`, which is the top-level enumeration every other endpoint
    # fans out over. All other endpoints require a `{workspace_id}` in their path.
    workspace_scoped: bool = True
    # For two-level fan-out: the name of the parent endpoint whose ids seed this child's path
    # (e.g. tasks fan out over `projects`, time_entries over `users`).
    fan_out_parent: Optional[str] = None
    # The path placeholder filled with each parent id during a two-level fan-out.
    parent_id_placeholder: Optional[str] = None
    # Query param name for the server-side timestamp filter, when the endpoint exposes one.
    # Only time-entries does (`start` filters entries that started after the given datetime).
    incremental_param: Optional[str] = None
    # HTTP method of the list request. Only the time-off listing deviates: Clockify serves it as a
    # POST whose filter criteria travel in the request body.
    method: Literal["GET", "POST"] = "GET"
    # jsonpath to the row list for endpoints that wrap it in an envelope. None means the response
    # body is the bare array.
    data_selector: Optional[str] = None
    # False for endpoints that accept no `page`/`page-size` params and return the whole collection
    # in one response.
    paginated: bool = True
    # Fail loud when `data_selector` matches nothing, rather than syncing zero rows off a changed
    # response shape.
    data_selector_required: bool = True
    # Static query params sent with every request to this endpoint, on top of paging and the
    # resolved path ids.
    extra_params: dict[str, Any] = field(default_factory=dict)


_TIME_ENTRY_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "time_interval_start",
        "type": IncrementalFieldType.DateTime,
        "field": "time_interval_start",
        "field_type": IncrementalFieldType.DateTime,
    },
]


CLOCKIFY_ENDPOINTS: dict[str, ClockifyEndpointConfig] = {
    # Top-level: the workspaces the API key's user belongs to. Every other endpoint fans out
    # over these ids. Workspaces are few per user and the endpoint is not paginated.
    "workspaces": ClockifyEndpointConfig(
        name="workspaces",
        path="/workspaces",
        primary_keys=["id"],
        workspace_scoped=False,
    ),
    "users": ClockifyEndpointConfig(
        name="users",
        path="/workspaces/{workspace_id}/users",
        primary_keys=["workspace_id", "id"],
    ),
    "clients": ClockifyEndpointConfig(
        name="clients",
        path="/workspaces/{workspace_id}/clients",
        primary_keys=["workspace_id", "id"],
    ),
    "projects": ClockifyEndpointConfig(
        name="projects",
        path="/workspaces/{workspace_id}/projects",
        primary_keys=["workspace_id", "id"],
    ),
    "tags": ClockifyEndpointConfig(
        name="tags",
        path="/workspaces/{workspace_id}/tags",
        primary_keys=["workspace_id", "id"],
    ),
    # Two-level fan-out: workspace -> project -> tasks. The task id is unique per project, so
    # the parent ids are part of the primary key to stay unique table-wide.
    "tasks": ClockifyEndpointConfig(
        name="tasks",
        path="/workspaces/{workspace_id}/projects/{project_id}/tasks",
        primary_keys=["workspace_id", "project_id", "id"],
        fan_out_parent="projects",
        parent_id_placeholder="project_id",
    ),
    # Two-level fan-out: workspace -> user -> time-entries. The only endpoint with a genuine
    # server-side time filter (`start`), so the only one that supports incremental sync.
    # Clockify returns time entries newest-first by start time and exposes no sort param, so
    # sort_mode is "desc"; the watermark is the (flattened) interval start.
    "time_entries": ClockifyEndpointConfig(
        name="time_entries",
        path="/workspaces/{workspace_id}/user/{user_id}/time-entries",
        primary_keys=["workspace_id", "user_id", "id"],
        incremental_fields=_TIME_ENTRY_INCREMENTAL_FIELDS,
        default_incremental_field="time_interval_start",
        partition_key="time_interval_start",
        sort_mode="desc",
        fan_out_parent="users",
        parent_id_placeholder="user_id",
        incremental_param="start",
    ),
    # Definitions for the custom field ids that time entries, projects and users carry. The
    # endpoint accepts no paging params and returns the whole collection in one response.
    "custom_fields": ClockifyEndpointConfig(
        name="custom_fields",
        path="/workspaces/{workspace_id}/custom-fields",
        primary_keys=["workspace_id", "id"],
        paginated=False,
    ),
    # Expense transactions. The rows sit two levels down the response envelope, and that envelope
    # is documented as nullable, so a workspace without expense tracking yields no rows rather
    # than a shape error.
    "expenses": ClockifyEndpointConfig(
        name="expenses",
        path="/workspaces/{workspace_id}/expenses",
        primary_keys=["workspace_id", "id"],
        data_selector="expenses.expenses",
        data_selector_required=False,
    ),
    # Category lookup for expenses. Clockify filters on `archived` with a default of false, so this
    # table holds the active categories — the same treatment clients/projects/tags already get.
    "expense_categories": ClockifyEndpointConfig(
        name="expense_categories",
        path="/workspaces/{workspace_id}/expenses/categories",
        primary_keys=["workspace_id", "id"],
        data_selector="categories",
    ),
    "invoices": ClockifyEndpointConfig(
        name="invoices",
        path="/workspaces/{workspace_id}/invoices",
        primary_keys=["workspace_id", "id"],
        data_selector="invoices",
    ),
    # Two-level fan-out: workspace -> invoice -> payments. Payment ids are documented per invoice,
    # so both parent ids are part of the primary key.
    "invoice_payments": ClockifyEndpointConfig(
        name="invoice_payments",
        path="/workspaces/{workspace_id}/invoices/{invoice_id}/payments",
        primary_keys=["workspace_id", "invoice_id", "id"],
        fan_out_parent="invoices",
        parent_id_placeholder="invoice_id",
    ),
    # The only POST listing. Paging travels in the body, where `pageSize` caps at 200.
    "time_off_requests": ClockifyEndpointConfig(
        name="time_off_requests",
        path="/workspaces/{workspace_id}/time-off/requests",
        primary_keys=["workspace_id", "id"],
        method="POST",
        data_selector="requests",
        page_size=200,
    ),
    # Timesheet approval state per user and period. The row's id sits inside the nested
    # `approvalRequest` object, flattened during sync. Paginating on an ascending id keeps pages
    # stable while approvals are submitted mid-sync; the endpoint exposes no timestamp filter, so
    # there is nothing to sync incrementally on.
    "approval_requests": ClockifyEndpointConfig(
        name="approval_requests",
        path="/workspaces/{workspace_id}/approval-requests",
        primary_keys=["workspace_id", "approval_request_id"],
        extra_params={"sort-column": "ID", "sort-order": "ASCENDING"},
    ),
    # Team grouping. Each row carries its members as `userIds`, so the group-members sub-resource
    # is not needed — Clockify serves it as POST/DELETE only. `includeTeamManagers` adds the
    # managers assigned to the group, which are omitted by default.
    "user_groups": ClockifyEndpointConfig(
        name="user_groups",
        path="/workspaces/{workspace_id}/user-groups",
        primary_keys=["workspace_id", "id"],
        extra_params={"sort-column": "ID", "sort-order": "ASCENDING", "includeTeamManagers": "true"},
    ),
}

ENDPOINTS = tuple(CLOCKIFY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLOCKIFY_ENDPOINTS.items()
}
