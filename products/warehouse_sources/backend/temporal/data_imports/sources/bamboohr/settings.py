from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# How records are laid out in a BambooHR JSON response.
#   "list"   — the records are a JSON array (either the whole body or under ``data_key``)
#   "dict"   — the records are a JSON object keyed by id (e.g. ``meta/users``); we take ``.values()``
#   "object" — the body is one record (a by-id detail endpoint), yielded as a single row
DataShape = Literal["list", "dict", "object"]

# How an endpoint's pages are walked.
#   "links"            — follow the absolute URL under ``_links.next``; classic endpoints carry no
#                        links at all and so return a single page
#   "single"           — the body is the whole response; never ask for a second page
#   "page_number"      — ``page``/``pageSize`` query params, walked until a page comes back empty
#   "ats_applications" — the ATS applications envelope (``paginationComplete`` + ``nextPageUrl``)
PaginationStyle = Literal["links", "single", "page_number", "ats_applications"]

# The employee-table history endpoints group their rows under a map of employee id, and only that
# map carries the employee id and the timestamp of their last change — see ``bamboohr.py``.
EMPLOYEE_TABLE_LAST_CHANGED = "lastChanged"
EMPLOYEE_TABLE_EMPLOYEE_ID = "employeeId"

# Goal comments are addressed by employee *and* goal, and the comment rows carry neither.
GOAL_ID = "goalId"

# BambooHR's org locations endpoint is the only one that takes a page size.
LOCATIONS_PAGE_SIZE = 500


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
    # Fan-out over a parent listing, for endpoints addressed by a single parent record.
    fanout: DependentEndpointConfig | None = None
    # Set when the endpoint is two fan-out levels deep, which the single-hop helper cannot express.
    custom_iterator: Literal["goal_comments"] | None = None
    # Static query params every request for this endpoint carries.
    params: dict[str, Any] = field(default_factory=dict)
    # Set when one request set cannot reach the whole collection: the endpoint is walked once per
    # variant and the results concatenated. Each variant must select a disjoint set of rows.
    param_variants: list[dict[str, Any]] = field(default_factory=list)
    pagination: PaginationStyle = "links"
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

_EMPLOYEE_GOALS_FANOUT = DependentEndpointConfig(
    parent_name="employees",
    resolve_param="employeeId",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": EMPLOYEE_TABLE_EMPLOYEE_ID},
    # Closed goals are left out unless the filter asks for every status.
    child_params={"filter": "status-all"},
)

# The defaults narrow the funnel to open positions and active applications, which would leave
# hired and rejected applications — the outcomes the funnel is measured by — out of the table.
_ATS_APPLICATION_PARAMS: dict[str, Any] = {
    "applicationStatus": "ALL",
    "jobStatusGroups": "ALL",
    "sortBy": "created_date",
    "sortOrder": "ASC",
}

_APPLICATION_FANOUT = DependentEndpointConfig(
    parent_name="applications",
    resolve_param="applicationId",
    resolve_field="id",
    # The detail body carries its own id, so nothing has to be copied off the parent row.
    include_from_parent=[],
    parent_params=_ATS_APPLICATION_PARAMS,
    # An application deleted between the listing and its detail fetch is not a sync failure.
    child_response_actions=[{"status_code": 404, "action": "ignore", "message": None}],
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
    "whos_out": BambooHREndpointConfig(
        name="whos_out",
        path="v1/time_off/whos_out",
        # Holiday entries and time-off entries number their ids separately, so the two can collide.
        primary_keys=["type", "id"],
        requires_date_window=True,
        # Without this the response is narrowed to the API user's saved Who's Out calendar filter.
        params={"filter": "off"},
    ),
    "locations": BambooHREndpointConfig(
        name="locations",
        path="v1/hris/org/locations",
        data_key="data",
        primary_keys=["id"],
        pagination="page_number",
        params={"pageSize": LOCATIONS_PAGE_SIZE},
        # The endpoint answers with active locations only, so archived ones are asked for
        # separately. Employees and job openings still point at locations after they are archived.
        param_variants=[{"filter": "archived eq false"}, {"filter": "archived eq true"}],
    ),
    "job_openings": BambooHREndpointConfig(
        name="job_openings",
        path="v1/applicant_tracking/jobs",
        primary_keys=["id"],
        # The default omits deleted positions, which synced applications still point at.
        params={"statusGroups": "ALL"},
    ),
    "applications": BambooHREndpointConfig(
        name="applications",
        path="v1/applicant_tracking/applications",
        data_key="applications",
        primary_keys=["id"],
        pagination="ats_applications",
        params=_ATS_APPLICATION_PARAMS,
    ),
    "application_details": BambooHREndpointConfig(
        name="application_details",
        path="v1/applicant_tracking/applications/{applicationId}",
        data_shape="object",
        pagination="single",
        primary_keys=["id"],
        fanout=_APPLICATION_FANOUT,
    ),
    "applicant_statuses": BambooHREndpointConfig(
        name="applicant_statuses",
        path="v1/applicant_tracking/statuses",
        primary_keys=["id"],
    ),
    "ats_locations": BambooHREndpointConfig(
        name="ats_locations",
        path="v1/applicant_tracking/locations",
        primary_keys=["id"],
    ),
    "employee_goals": BambooHREndpointConfig(
        name="employee_goals",
        path="v1/performance/employees/{employeeId}/goals",
        data_key="goals",
        primary_keys=[EMPLOYEE_TABLE_EMPLOYEE_ID, "id"],
        fanout=_EMPLOYEE_GOALS_FANOUT,
    ),
    "employee_goal_comments": BambooHREndpointConfig(
        name="employee_goal_comments",
        path="v1/performance/employees/{employeeId}/goals/{goalId}/comments",
        data_key="comments",
        primary_keys=[EMPLOYEE_TABLE_EMPLOYEE_ID, GOAL_ID, "id"],
        custom_iterator="goal_comments",
    ),
}

ENDPOINTS = tuple(BAMBOOHR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BAMBOOHR_ENDPOINTS.items()
}
