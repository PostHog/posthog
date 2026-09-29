from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

# Float caps `per-page` at 200 (default 50). Always request the max to minimise round trips.
PER_PAGE = 200
# The Delete Log endpoints use cursor pagination and accept a `limit` of up to 500.
DELETE_LOG_LIMIT = 500

# `/public-holidays` defaults to the current year alone, which would hide the holidays behind any
# historical logged time. `start_date`/`end_date` override that default, so span a fixed window
# around today instead.
PUBLIC_HOLIDAY_YEARS_BACK = 3
PUBLIC_HOLIDAY_YEARS_AHEAD = 1

# The report endpoints require a `start_date`/`end_date` and return the aggregate over it with no
# pagination, so `/reports/people` is walked one calendar month at a time to give the table a
# monthly grain instead of a single window whose meaning shifts every sync.
REPORT_LOOKBACK_MONTHS = 12

PaginationMode = Literal["page", "cursor", "report_window"]


@dataclass
class FloatEndpointConfig:
    name: str
    # Path under the `/v3` base, e.g. "/people". Verified to exist against the live API (401 behind
    # auth vs 404 for unknown paths). Note the hyphenated resources: `/project-tasks`, `/timeoff-types`,
    # `/logged-time`.
    path: str
    # Float ids follow the `<resource>_id` convention (e.g. `people_id`, `project_id`). These are the
    # table's declared primary keys; sourced from Float's documented object shapes. Because every stream
    # is full-refresh (replace), a mismatch here is metadata-only and cannot accumulate duplicate rows.
    primary_keys: list[str]
    # Stable creation-time field to partition by. Only set where Float is known to return a `created`
    # timestamp on every row — an absent partition column would fail the write. None disables partitioning.
    partition_key: str | None = None
    # Core resources use page-number pagination (`page`/`per-page` + `X-Pagination-*` headers). The
    # Delete Log endpoints use cursor pagination (`cursor`/`limit` + `X-Pagination-Next-Cursor`), and
    # the report endpoints are unpaginated windows walked a month at a time.
    pagination: PaginationMode = "page"
    # Send an explicit `start_date`/`end_date` instead of accepting the endpoint's default range.
    date_window: bool = False
    should_sync_default: bool = True


# Float's public API exposes no general modified-since filter on its core resources, so every stream is
# full refresh. The Delete Log and logged-time streams are documented incremental candidates, but Float
# offers no server-side timestamp filter we could verify without a live token, so they ship full refresh
# too (see the source docstring). Keep this in mind before flipping any `supports_incremental` on.
FLOAT_ENDPOINTS: dict[str, FloatEndpointConfig] = {
    "people": FloatEndpointConfig(name="people", path="/people", primary_keys=["people_id"], partition_key="created"),
    "accounts": FloatEndpointConfig(name="accounts", path="/accounts", primary_keys=["account_id"]),
    "departments": FloatEndpointConfig(name="departments", path="/departments", primary_keys=["department_id"]),
    "clients": FloatEndpointConfig(name="clients", path="/clients", primary_keys=["client_id"]),
    "projects": FloatEndpointConfig(
        name="projects", path="/projects", primary_keys=["project_id"], partition_key="created"
    ),
    "project_stages": FloatEndpointConfig(
        name="project_stages", path="/project-stages", primary_keys=["id"], partition_key="created"
    ),
    "phases": FloatEndpointConfig(name="phases", path="/phases", primary_keys=["phase_id"]),
    "tasks": FloatEndpointConfig(name="tasks", path="/tasks", primary_keys=["task_id"], partition_key="created"),
    "project_tasks": FloatEndpointConfig(name="project_tasks", path="/project-tasks", primary_keys=["task_meta_id"]),
    "project_expenses": FloatEndpointConfig(
        name="project_expenses", path="/project-expenses", primary_keys=["id"], partition_key="created"
    ),
    "milestones": FloatEndpointConfig(name="milestones", path="/milestones", primary_keys=["milestone_id"]),
    "timeoffs": FloatEndpointConfig(
        name="timeoffs", path="/timeoffs", primary_keys=["timeoff_id"], partition_key="created"
    ),
    "timeoff_types": FloatEndpointConfig(name="timeoff_types", path="/timeoff-types", primary_keys=["timeoff_type_id"]),
    "logged_time": FloatEndpointConfig(
        name="logged_time", path="/logged-time", primary_keys=["logged_time_id"], partition_key="created"
    ),
    "status": FloatEndpointConfig(name="status", path="/status", primary_keys=["status_id"]),
    "roles": FloatEndpointConfig(name="roles", path="/roles", primary_keys=["id"]),
    "holidays": FloatEndpointConfig(name="holidays", path="/holidays", primary_keys=["holiday_id"]),
    "public_holidays": FloatEndpointConfig(
        name="public_holidays",
        path="/public-holidays",
        # Float documents `id` as the holiday's id *per region*, so it is only unique within a region.
        primary_keys=["id", "region"],
        date_window=True,
    ),
    "rate_cards": FloatEndpointConfig(name="rate_cards", path="/rate-cards", primary_keys=["rate_card_id"]),
    "currencies": FloatEndpointConfig(name="currencies", path="/currencies", primary_keys=["currency_id"]),
    "reports_people": FloatEndpointConfig(
        name="reports_people",
        path="/reports/people",
        # One row per person per report window, so `people_id` alone repeats across windows.
        primary_keys=["people_id", "start_date"],
        partition_key="start_date",
        pagination="report_window",
    ),
    # Delete Log endpoints — cursor pagination, append-only tombstones. Niche, so off by default.
    "deleted_tasks": FloatEndpointConfig(
        name="deleted_tasks",
        path="/deleted/tasks",
        primary_keys=["task_id"],
        pagination="cursor",
        should_sync_default=False,
    ),
    "deleted_timeoffs": FloatEndpointConfig(
        name="deleted_timeoffs",
        path="/deleted/timeoffs",
        primary_keys=["timeoff_id"],
        pagination="cursor",
        should_sync_default=False,
    ),
    "deleted_logged_time": FloatEndpointConfig(
        name="deleted_logged_time",
        path="/deleted/logged-time",
        primary_keys=["logged_time_id"],
        pagination="cursor",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(FLOAT_ENDPOINTS.keys())

# Every stream is full refresh — no endpoint advertises a server-side incremental cursor today.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in FLOAT_ENDPOINTS}
