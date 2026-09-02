from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField

# Workday's REST collection endpoints default to 20 objects per page and cap `limit` at 100.
DEFAULT_PAGE_SIZE = 100

# Most of the catalog lives in the Staffing service, which is versioned per service
# (`/ccx/api/staffing/v7/{tenant}/...`). That version is what the source pins.
STAFFING_SERVICE = "staffing"
# The Common service is served straight off `/ccx/api/v1/{tenant}/...` with no service segment,
# and its v1 has never been re-versioned, so it is not part of the pin.
COMMON_SERVICE = "common"


@dataclass(frozen=True)
class WorkdayEndpointConfig:
    name: str
    resource: str
    service: str = STAFFING_SERVICE
    primary_key: str = "id"


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
}

ENDPOINTS = tuple(WORKDAY_ENDPOINTS.keys())

# Workday's server-side `Updated_From` / `Updated_Through` range filters live on the SOAP web
# services, not on the REST collections exposed here, so every endpoint is full-refresh only.
# Advertising an incremental cursor we can't push down would re-read the whole collection each
# run at the same API cost while pretending otherwise.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in WORKDAY_ENDPOINTS}


def build_endpoint_path(config: WorkdayEndpointConfig, tenant: str, staffing_version: str) -> str:
    """Path of a collection endpoint relative to the `/ccx/api` base URL."""
    if config.service == COMMON_SERVICE:
        return f"/v1/{tenant}/{config.resource}"
    return f"/{config.service}/{staffing_version}/{tenant}/{config.resource}"
