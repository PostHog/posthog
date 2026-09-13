from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# How records are laid out in a BambooHR JSON response.
#   "list" — the records are a JSON array (either the whole body or under ``data_key``)
#   "dict" — the records are a JSON object keyed by id (e.g. ``meta/users``); we take ``.values()``
DataShape = Literal["list", "dict"]

# The employee-table history endpoints group their rows under a map of employee id, and only that
# map carries the employee id and the timestamp of their last change — see ``bamboohr.py``.
EMPLOYEE_TABLE_LAST_CHANGED = "lastChanged"
EMPLOYEE_TABLE_EMPLOYEE_ID = "employeeId"


@dataclass(frozen=True)
class ChunkedDateWindow:
    """Walk an endpoint's date range in slices instead of asking for all of it at once.

    For endpoints that take a start/end window and return every matching row in one unpaginated
    response, so a wide window puts a whole company's history in a single response body.
    """

    history_days: int
    chunk_days: int


@dataclass(frozen=False)
class BambooHREndpointConfig:
    name: str
    # Path relative to ``/api/gateway.php/{subdomain}/``, including the API version segment.
    # BambooHR revises individual endpoints under a ``v1_1`` segment of the same v1 API, so the
    # segment belongs to the endpoint rather than to the source.
    path: str
    primary_keys: list[str]
    # JSON key holding the records, or ``None`` when the body itself is the collection.
    data_key: str | None = None
    data_shape: DataShape = "list"
    # Some endpoints (time off) reject requests without an explicit date window.
    requires_date_window: bool = False
    # Set on the employee-table history streams, naming the BambooHR table they read.
    employee_table: str | None = None
    # Set when the endpoint's window has to be fetched in slices.
    chunked_date_window: ChunkedDateWindow | None = None
    # Fan-out over the employee directory, for endpoints addressed by a single employee.
    fanout: DependentEndpointConfig | None = None
    # Only the employee-table history endpoints expose a verified server-side "changed since"
    # filter; every other stream is full-refresh. See bamboohr.py.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # BambooHR list endpoints take no page-size parameter; declared to satisfy the fan-out
    # helper's endpoint protocol.
    page_size: int = 100


_EMPLOYEE_FANOUT = DependentEndpointConfig(
    parent_name="employees",
    resolve_param="employeeId",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": EMPLOYEE_TABLE_EMPLOYEE_ID},
)


def _employee_table_endpoint(name: str, table: str) -> BambooHREndpointConfig:
    return BambooHREndpointConfig(
        name=name,
        path=f"v1/employees/changed/tables/{table}",
        employee_table=table,
        # The row id is unique within its table, not across employees, so pair the two.
        primary_keys=[EMPLOYEE_TABLE_EMPLOYEE_ID, "id"],
        incremental_fields=[incremental_field(EMPLOYEE_TABLE_LAST_CHANGED)],
        default_incremental_field=EMPLOYEE_TABLE_LAST_CHANGED,
    )


BAMBOOHR_ENDPOINTS: dict[str, BambooHREndpointConfig] = {
    "employees": BambooHREndpointConfig(
        name="employees",
        path="v1/employees/directory",
        data_key="employees",
        primary_keys=["id"],
    ),
    "employee_job_info": _employee_table_endpoint("employee_job_info", "jobInfo"),
    "employee_compensation": _employee_table_endpoint("employee_compensation", "compensation"),
    "employee_employment_status": _employee_table_endpoint("employee_employment_status", "employmentStatus"),
    "time_off_requests": BambooHREndpointConfig(
        name="time_off_requests",
        path="v1/time_off/requests",
        primary_keys=["id"],
        requires_date_window=True,
    ),
    "time_off_types": BambooHREndpointConfig(
        name="time_off_types",
        path="v1/meta/time_off/types",
        data_key="timeOffTypes",
        primary_keys=["id"],
    ),
    "time_off_policies": BambooHREndpointConfig(
        name="time_off_policies",
        path="v1/meta/time_off/policies",
        primary_keys=["id"],
    ),
    "employee_time_off_policies": BambooHREndpointConfig(
        name="employee_time_off_policies",
        # v1.1 of this endpoint also returns manual and unlimited policies, which v1 leaves out.
        path="v1_1/employees/{employeeId}/time_off/policies",
        primary_keys=[EMPLOYEE_TABLE_EMPLOYEE_ID, "timeOffPolicyId"],
        fanout=_EMPLOYEE_FANOUT,
    ),
    "employee_time_off_balances": BambooHREndpointConfig(
        name="employee_time_off_balances",
        path="v1/employees/{employeeId}/time_off/calculator",
        primary_keys=[EMPLOYEE_TABLE_EMPLOYEE_ID, "timeOffType"],
        fanout=_EMPLOYEE_FANOUT,
    ),
    "timesheet_entries": BambooHREndpointConfig(
        name="timesheet_entries",
        path="v1/time_tracking/timesheet_entries",
        primary_keys=["id"],
        # BambooHR rejects a window reaching further back than a year, so a year of entries is all
        # this endpoint can ever return. A month per request keeps each response body bounded.
        chunked_date_window=ChunkedDateWindow(history_days=365, chunk_days=31),
    ),
    "meta_fields": BambooHREndpointConfig(
        name="meta_fields",
        path="v1/meta/fields",
        primary_keys=["id"],
    ),
    "meta_lists": BambooHREndpointConfig(
        name="meta_lists",
        path="v1/meta/lists",
        primary_keys=["fieldId"],
    ),
    "meta_users": BambooHREndpointConfig(
        name="meta_users",
        path="v1/meta/users",
        data_shape="dict",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(BAMBOOHR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BAMBOOHR_ENDPOINTS.items()
}
