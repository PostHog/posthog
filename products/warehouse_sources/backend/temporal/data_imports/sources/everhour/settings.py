from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# No real planning horizon reaches this far, and Everhour drops assignments ending after ``to``.
ASSIGNMENTS_DAYS_AHEAD = 5 * 365

# How an endpoint's request URLs are derived:
#   "none"     -> a single top-level list endpoint (no parent fan-out)
#   "project"  -> one request per project (fan out over /projects)
FanOut = Literal["none", "project"]


@dataclass
class EverhourEndpointConfig:
    name: str
    fan_out: FanOut
    # Relative path appended to the API base. Fan-out task paths carry a single ``{project_id}``
    # placeholder (the parent project id); top-level paths have no placeholder.
    path_template: str
    # Everhour caps most list endpoints at a small page size and paginates with limit/offset.
    # /time-records is capped at 50 per page; the reference endpoints comfortably take 100.
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fields identifying a row while paginating, used to spot a page the API re-served because it
    # ignored ``offset``. Kept separate from ``primary_keys`` because an injected parent id is only
    # added to a row after the check, and because not every endpoint returns an ``id``.
    dedupe_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation/work-date field used for datetime partitioning. Never an "updated_at"-style
    # field — partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    partition_format: Literal["month", "week", "day", "hour"] = "month"
    # When set, the endpoint accepts ``from``/``to`` (YYYY-MM-DD) date-range filters, enabling
    # server-side date-windowed incremental sync.
    supports_date_window: bool = False
    # How far past today the window's ``to`` bound reaches. Endpoints holding scheduled future work
    # need this; leaving it at 0 would drop every planned row.
    window_days_ahead: int = 0
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # For fan-out endpoints: inject the parent project id into each row under this key, so the
    # composite primary key stays unique table-wide (a task can belong to multiple projects).
    include_parent_id_as: Optional[str] = None
    # Whether the table is selected for sync by default in the UI.
    should_sync_default: bool = True


EVERHOUR_ENDPOINTS: dict[str, EverhourEndpointConfig] = {
    "clients": EverhourEndpointConfig(
        name="clients",
        fan_out="none",
        path_template="/clients",
    ),
    "projects": EverhourEndpointConfig(
        name="projects",
        fan_out="none",
        path_template="/projects",
    ),
    "users": EverhourEndpointConfig(
        name="users",
        fan_out="none",
        path_template="/team/users",
    ),
    "tasks": EverhourEndpointConfig(
        name="tasks",
        fan_out="project",
        path_template="/projects/{project_id}/tasks",
        primary_keys=["project_id", "id"],
        include_parent_id_as="project_id",
    ),
    "time_records": EverhourEndpointConfig(
        name="time_records",
        fan_out="none",
        path_template="/time-records",
        page_size=50,  # /time-records caps the page size at 50
        partition_key="date",
        supports_date_window=True,
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "invoices": EverhourEndpointConfig(
        name="invoices",
        fan_out="none",
        path_template="/invoices",
        # Line items come back nested under `invoiceItems`, and GET /invoices/{id} returns the same
        # object the list does, so there is nothing further to fan out for.
        partition_key="createdAt",
    ),
    "expenses": EverhourEndpointConfig(
        name="expenses",
        fan_out="none",
        path_template="/expenses",
        partition_key="date",
    ),
    "timecards": EverhourEndpointConfig(
        name="timecards",
        fan_out="none",
        path_template="/timecards",
        # A timecard carries no id of its own; a user holds at most one card per calendar date.
        primary_keys=["user", "date"],
        dedupe_keys=["user", "date"],
        partition_key="date",
        # /timecards defaults to the last two weeks, so the window has to be passed explicitly to
        # reach any history at all.
        supports_date_window=True,
    ),
    "assignments": EverhourEndpointConfig(
        name="assignments",
        fan_out="none",
        path_template="/resource-planner/assignments",
        # An assignment carries no creation timestamp, and its startDate moves whenever the work is
        # replanned, so there is no stable partition key to use.
        supports_date_window=True,
        window_days_ahead=ASSIGNMENTS_DAYS_AHEAD,
    ),
}

ENDPOINTS = tuple(EVERHOUR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EVERHOUR_ENDPOINTS.items() if config.incremental_fields
}
