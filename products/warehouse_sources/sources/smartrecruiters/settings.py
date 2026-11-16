from dataclasses import field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

BASE_URL = "https://api.smartrecruiters.com"

# Every list endpoint we read caps `limit` at 100. The Reporting API allows 1000, but the report
# catalog is small, so one page size keeps the endpoints alike.
PAGE_SIZE = 100

# `cursor`: the body carries the next page id, sent back as a query param.
# `offset`: limit/offset paging, stopped by `totalFound`.
# `single`: the endpoint returns the whole collection in one response.
PaginationType = Literal["cursor", "offset", "single"]

UPDATED_ON_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updatedOn",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedOn",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@frozen
class SmartRecruitersEndpointConfig:
    name: str
    path: str
    pagination: PaginationType
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by, or None when the rows carry none.
    partition_key: Optional[str] = None
    # Set only where the list endpoint takes a server-side `updatedAfter` filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    page_size_param: Optional[str] = "limit"
    cursor_path: str = "nextPageId"
    cursor_param: str = "pageId"
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE


def _job_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="jobs",
        resolve_param="job_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "job_id"},
        # `pageId` paging on /jobs only returns every row when sorted by job id.
        parent_params={"limit": PAGE_SIZE, "sort": "job_id"},
        # A job deleted between the parent listing and its child request is not an error.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


SMARTRECRUITERS_ENDPOINTS: dict[str, SmartRecruitersEndpointConfig] = {
    "jobs": SmartRecruitersEndpointConfig(
        name="jobs",
        path="/jobs",
        pagination="cursor",
        partition_key="createdOn",
        incremental_fields=UPDATED_ON_INCREMENTAL_FIELDS,
        default_incremental_field="updatedOn",
        # `pageId` paging needs `sort=job_id`; the default sort can skip rows between pages.
        params={"sort": "job_id"},
    ),
    "candidates": SmartRecruitersEndpointConfig(
        name="candidates",
        path="/candidates",
        pagination="cursor",
        partition_key="createdOn",
        incremental_fields=UPDATED_ON_INCREMENTAL_FIELDS,
        default_incremental_field="updatedOn",
    ),
    "users": SmartRecruitersEndpointConfig(
        name="users",
        path="/user-api/v201804/users",
        pagination="cursor",
        incremental_fields=UPDATED_ON_INCREMENTAL_FIELDS,
        default_incremental_field="updatedOn",
    ),
    # /offers only filters on creation time, which misses status changes, so it is full refresh.
    "offers": SmartRecruitersEndpointConfig(
        name="offers",
        path="/offers",
        pagination="offset",
        partition_key="createdOn",
    ),
    "reports": SmartRecruitersEndpointConfig(
        name="reports",
        path="/reporting-api/v201804/reports",
        pagination="cursor",
        primary_keys=["reportId"],
        partition_key="creationDate",
        cursor_path="nextPage",
        cursor_param="page",
    ),
    "predefined_locations": SmartRecruitersEndpointConfig(
        name="predefined_locations",
        path="/configuration/predefined-locations",
        pagination="cursor",
        page_size_param="pageSize",
    ),
    "departments": SmartRecruitersEndpointConfig(
        name="departments",
        path="/configuration/departments",
        pagination="single",
        page_size_param=None,
    ),
    "hiring_processes": SmartRecruitersEndpointConfig(
        name="hiring_processes",
        path="/configuration/hiring-processes",
        pagination="single",
        page_size_param=None,
    ),
    "rejection_reasons": SmartRecruitersEndpointConfig(
        name="rejection_reasons",
        path="/configuration/rejection-reasons",
        pagination="single",
        page_size_param=None,
    ),
    "withdrawal_reasons": SmartRecruitersEndpointConfig(
        name="withdrawal_reasons",
        path="/configuration/withdrawal-reasons",
        pagination="single",
        page_size_param=None,
    ),
    # A hiring team member id is a user id, so the same user appears on many jobs.
    "job_hiring_team": SmartRecruitersEndpointConfig(
        name="job_hiring_team",
        path="/jobs/{job_id}/hiring-team",
        pagination="single",
        primary_keys=["job_id", "id"],
        page_size_param=None,
        fanout=_job_fanout(),
    ),
    "job_positions": SmartRecruitersEndpointConfig(
        name="job_positions",
        path="/jobs/{job_id}/positions",
        pagination="single",
        primary_keys=["job_id", "id"],
        partition_key="createdOn",
        page_size_param=None,
        fanout=_job_fanout(),
    ),
}

ENDPOINTS = tuple(SMARTRECRUITERS_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SMARTRECRUITERS_ENDPOINTS.items() if config.incremental_fields
}
