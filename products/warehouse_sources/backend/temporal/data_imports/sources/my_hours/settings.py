from dataclasses import dataclass, field
from datetime import date
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class MyHoursEndpointConfig:
    name: str
    path: str
    # My Hours object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fanout: DependentEndpointConfig | None = None
    # Read by the shared fan-out helper. My Hours list endpoints are unpaginated, so no page size is sent.
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = 0


TIME_LOGS_ENDPOINT = "time_logs"
PROJECT_TASKS_ENDPOINT = "project_tasks"

# The activity report needs an explicit date window and returns the whole window in one response,
# so a full sync walks fixed windows from this floor to today.
TIME_LOGS_FIRST_DATE = date(2010, 1, 1)
TIME_LOGS_WINDOW_DAYS = 31
# Time logs are routinely back-dated (weekly timesheets, late edits), so incremental syncs re-read
# this window behind the watermark. Merge on `logId` dedupes the overlap.
TIME_LOGS_LOOKBACK_SECONDS = 30 * 24 * 60 * 60

_PROJECT_FANOUT = DependentEndpointConfig(
    parent_name="projects",
    resolve_param="project_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "projectId"},
    # A project deleted between the project listing and its child request.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

# My Hours REST API list endpoints. The plain list endpoints are full refresh only: they expose no
# row-level pagination and no updated-since cursor. `time_logs` reads the account-wide activity
# report, which filters server-side by log date.
MY_HOURS_ENDPOINTS: dict[str, MyHoursEndpointConfig] = {
    "clients": MyHoursEndpointConfig(name="clients", path="/Clients"),
    "projects": MyHoursEndpointConfig(name="projects", path="/Projects/getAll"),
    "tags": MyHoursEndpointConfig(name="tags", path="/Tags"),
    "users": MyHoursEndpointConfig(name="users", path="/Users/getAll"),
    TIME_LOGS_ENDPOINT: MyHoursEndpointConfig(
        name=TIME_LOGS_ENDPOINT, path="/Reports/activitydx", primary_keys=["logId"]
    ),
    PROJECT_TASKS_ENDPOINT: MyHoursEndpointConfig(
        name=PROJECT_TASKS_ENDPOINT,
        path="/Projects/{project_id}/tasklist",
        primary_keys=["projectId", "id"],
        fanout=_PROJECT_FANOUT,
    ),
    "project_members": MyHoursEndpointConfig(
        name="project_members",
        path="/Projects/{project_id}/userlist",
        primary_keys=["projectId", "userId"],
        fanout=_PROJECT_FANOUT,
    ),
}

ENDPOINTS = tuple(MY_HOURS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TIME_LOGS_ENDPOINT: [
        {
            "label": "date",
            "type": IncrementalFieldType.DateTime,
            "field": "date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
