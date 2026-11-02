from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Single global host — Power BI resolves tenant data residency server-side.
BASE_URL = "https://api.powerbi.com/v1.0/myorg/admin"
# Entra ID (Azure AD) token endpoint; the tenant id is interpolated into the path.
LOGIN_BASE_URL = "https://login.microsoftonline.com"
# Client-credentials scope for the Power BI / Fabric REST API.
TOKEN_SCOPE = "https://analysis.windows.net/powerbi/api/.default"

# Activity events are only retained for a rolling window, and each request must cover a
# single UTC day. Warehousing them past this window is the point of the table, so the first
# sync can only reach as far back as the API still serves.
ACTIVITY_EVENTS_RETENTION_DAYS = 28

# `$top` ceiling documented for the AsAdmin inventory list endpoints.
ODATA_PAGE_SIZE = 5000
# The refreshables reference only documents paging "beyond the first 1000", so ask for no more than
# that: a page the server silently truncates below `$top` would end the walk early.
REFRESHABLES_PAGE_SIZE = 1000

# Hard caps so a misbehaving continuation token or an `$skip` walk that never shortens
# can't spin forever. Both are far above any realistic tenant.
MAX_CONTINUATION_PAGES = 2000
MAX_ODATA_PAGES = 200

ACTIVITY_EVENTS_ENDPOINT = "activity_events"


@dataclass(frozen=True)
class PowerBiAdminEndpointConfig:
    name: str
    # Path under BASE_URL.
    path: str
    primary_keys: list[str]
    description: str
    # Response key the rows live under.
    data_key: str = "value"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime column for datetime partitioning (None = no datetime partitioning).
    partition_key: Optional[str] = None
    # OData `$top`/`$skip` paging. Activity events use continuation tokens instead, and
    # `capacities` returns the whole tenant list in one response.
    supports_odata_paging: bool = True
    page_size: int = ODATA_PAGE_SIZE
    # Extra query params sent on every page, such as `$expand`.
    params: dict[str, str] = field(default_factory=dict)
    # When set, each parent row's list under `child_key` becomes the table's rows, stamped
    # with the parent `id` as `parent_id_column`. Expanding children inline on the parent
    # list costs one request per page instead of one per parent against a 200/hour limit.
    child_key: Optional[str] = None
    parent_id_column: Optional[str] = None


POWER_BI_ADMIN_ENDPOINTS: dict[str, PowerBiAdminEndpointConfig] = {
    ACTIVITY_EVENTS_ENDPOINT: PowerBiAdminEndpointConfig(
        name=ACTIVITY_EVENTS_ENDPOINT,
        path="/activityevents",
        primary_keys=["Id"],
        description="Tenant audit events (views, edits, exports, shares) for Power BI and Fabric items",
        data_key="activityEventEntities",
        # `CreationTime` is when the event happened and never changes, so it is safe as both
        # the cursor and the partition key.
        incremental_fields=[incremental_field("CreationTime")],
        partition_key="CreationTime",
        supports_odata_paging=False,
    ),
    "groups": PowerBiAdminEndpointConfig(
        name="groups",
        path="/groups",
        primary_keys=["id"],
        description="Every workspace in the tenant, including personal and orphaned workspaces",
    ),
    "datasets": PowerBiAdminEndpointConfig(
        name="datasets",
        path="/datasets",
        primary_keys=["id"],
        description="Every semantic model (dataset) in the tenant",
    ),
    "reports": PowerBiAdminEndpointConfig(
        name="reports",
        path="/reports",
        primary_keys=["id"],
        description="Every report in the tenant",
    ),
    "dashboards": PowerBiAdminEndpointConfig(
        name="dashboards",
        path="/dashboards",
        primary_keys=["id"],
        description="Every dashboard in the tenant",
    ),
    "dataflows": PowerBiAdminEndpointConfig(
        name="dataflows",
        path="/dataflows",
        primary_keys=["objectId"],
        description="Every dataflow in the tenant",
    ),
    "capacities": PowerBiAdminEndpointConfig(
        name="capacities",
        path="/capacities",
        primary_keys=["id"],
        description="Premium and Fabric capacities assigned to the tenant",
        supports_odata_paging=False,
    ),
    "dashboard_tiles": PowerBiAdminEndpointConfig(
        name="dashboard_tiles",
        path="/dashboards",
        primary_keys=["dashboard_id", "id"],
        description="Tiles on every dashboard in the tenant, with the report and dataset behind each tile",
        params={"$expand": "tiles"},
        child_key="tiles",
        parent_id_column="dashboard_id",
    ),
    "refreshables": PowerBiAdminEndpointConfig(
        name="refreshables",
        path="/capacities/refreshables",
        primary_keys=["id"],
        description="Refresh statistics for every semantic model on a capacity over the last seven days",
        page_size=REFRESHABLES_PAGE_SIZE,
        params={"$expand": "capacity,group"},
    ),
}

ENDPOINTS = tuple(POWER_BI_ADMIN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in POWER_BI_ADMIN_ENDPOINTS.items()
}
