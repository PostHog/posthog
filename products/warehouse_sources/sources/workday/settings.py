from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

# Workday's REST collection endpoints default to 20 objects per page and cap `limit` at 100.
DEFAULT_PAGE_SIZE = 100

# Most of the catalog lives in the Staffing service, which is versioned per service
# (`/ccx/api/staffing/v7/{tenant}/...`). That version is what the source pins.
STAFFING_SERVICE = "staffing"
# The Common service is served straight off `/ccx/api/v1/{tenant}/...` with no service segment,
# and its v1 has never been re-versioned, so it is not part of the pin.
COMMON_SERVICE = "common"
# Time Tracking is versioned separately from Staffing, so the Staffing pin does not move it.
TIME_TRACKING_SERVICE = "timeTracking"
TIME_TRACKING_VERSION = "v7"

# Per-worker sub-collections of the Common service. The child path binds the worker's Workday ID.
_PER_WORKER_FANOUT = DependentEndpointConfig(
    parent_name="workers",
    resolve_param="worker_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "worker_id"},
)


@dataclass(frozen=True)
class WorkdayEndpointConfig:
    name: str
    resource: str
    service: str = STAFFING_SERVICE
    primary_keys: tuple[str, ...] = ("id",)
    # Workday's `values` prompt lists document no `limit` / `offset`, so they are read in one request.
    paginated: bool = True
    fanout: Optional[DependentEndpointConfig] = None


WORKDAY_ENDPOINTS: dict[str, WorkdayEndpointConfig] = {
    "workers": WorkdayEndpointConfig(name="workers", resource="workers", service=COMMON_SERVICE),
    "jobs": WorkdayEndpointConfig(name="jobs", resource="jobs"),
    "job_profiles": WorkdayEndpointConfig(name="job_profiles", resource="jobProfiles"),
    "job_families": WorkdayEndpointConfig(name="job_families", resource="jobFamilies"),
    "supervisory_organizations": WorkdayEndpointConfig(
        name="supervisory_organizations", resource="supervisoryOrganizations"
    ),
    "job_changes": WorkdayEndpointConfig(name="job_changes", resource="jobChanges"),
    "organization_assignment_changes": WorkdayEndpointConfig(
        name="organization_assignment_changes", resource="organizationAssignmentChanges"
    ),
    "locations": WorkdayEndpointConfig(name="locations", resource="values/jobChangesGroup/locations/", paginated=False),
    "worker_time_blocks": WorkdayEndpointConfig(
        name="worker_time_blocks", resource="workerTimeBlocks", service=TIME_TRACKING_SERVICE
    ),
    # Pay slip and history ids are only documented as unique per worker, so the worker is in the key.
    "worker_pay_slips": WorkdayEndpointConfig(
        name="worker_pay_slips",
        resource="workers/{worker_id}/paySlips",
        service=COMMON_SERVICE,
        primary_keys=("worker_id", "id"),
        fanout=_PER_WORKER_FANOUT,
    ),
    "worker_history": WorkdayEndpointConfig(
        name="worker_history",
        resource="workers/{worker_id}/history",
        service=COMMON_SERVICE,
        primary_keys=("worker_id", "id"),
        fanout=_PER_WORKER_FANOUT,
    ),
}

ENDPOINTS = tuple(WORKDAY_ENDPOINTS.keys())

# Workday's server-side `Updated_From` / `Updated_Through` range filters live on the SOAP web
# services, not on the REST collections exposed here, so every endpoint is full-refresh only.
# Advertising an incremental cursor we can't push down would re-read the whole collection each
# run at the same API cost while pretending otherwise. `workerTimeBlocks` does take
# `fromDate` / `toDate`, but they filter on the block's calendar date, and a block's status
# changes after that date when it is submitted and approved.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in WORKDAY_ENDPOINTS}


def build_endpoint_path(config: WorkdayEndpointConfig, tenant: str, staffing_version: str) -> str:
    """Path of a collection endpoint relative to the `/ccx/api` base URL."""
    if config.service == COMMON_SERVICE:
        return f"/v1/{tenant}/{config.resource}"
    if config.service == TIME_TRACKING_SERVICE:
        return f"/{config.service}/{TIME_TRACKING_VERSION}/{tenant}/{config.resource}"
    return f"/{config.service}/{staffing_version}/{tenant}/{config.resource}"


@dataclass(frozen=True)
class FanoutEndpoint:
    """The endpoint shape `build_dependent_resource` reads, with the tenant path already resolved."""

    name: str
    path: str
    page_size: int = DEFAULT_PAGE_SIZE
    default_incremental_field: Optional[str] = None
    incremental_fields: list[Any] = field(default_factory=list)
