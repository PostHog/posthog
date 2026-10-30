from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

# Scaleway exposes three different pagination dialects across its products, so each endpoint declares
# which one it uses:
#   - "page_size": `page` + `page_size` query params, body wraps `{"<key>": [...], "total_count": N}`
#     (IAM, Account, Billing).
#   - "per_page":  `page` + `per_page` query params, body is `{"<key>": [...]}` and the total lives in
#     the `X-Total-Count` response header (Instance).
#   - "token":     `page_size` + `page_token` query params, body carries `next_page_token`
#     (Audit Trail).
Pagination = Literal["page_size", "per_page", "token"]

# A handful of Scaleway products are region- or zone-scoped in the path, so the connector iterates the
# scope list and substitutes it into `{region}` / `{zone}` before requesting.
#   - "billing_period": one pass per month of the trailing consumption window, sent as `billing_period`.
#   - "k8s_cluster": one pass per Kubernetes cluster, listed from every region in `scope_values`, which
#     fills both `{region}` and `{cluster_id}`.
Scope = Literal["none", "region", "zone", "billing_period", "k8s_cluster"]

# Max items per page allowed by every paginated Scaleway list endpoint.
PAGE_SIZE = 100

# Audit Trail is region-scoped in the path; only fr-par and nl-ams expose it today (pl-waw does not).
AUDIT_TRAIL_REGIONS = ["fr-par", "nl-ams"]

# Regions listed in the Kubernetes and Managed Database OpenAPI schemas.
K8S_REGIONS = ["fr-par", "nl-ams", "pl-waw", "it-mil"]
RDB_REGIONS = ["fr-par", "nl-ams", "pl-waw"]

# Instance servers are zone-scoped in the path. The connector fans out over every generally-available
# zone; zones with no servers simply return an empty page.
INSTANCE_ZONES = [
    "fr-par-1",
    "fr-par-2",
    "fr-par-3",
    "nl-ams-1",
    "nl-ams-2",
    "nl-ams-3",
    "pl-waw-1",
    "pl-waw-2",
    "pl-waw-3",
    "it-mil-1",
]

# Audit Trail's list endpoint defaults `recorded_after` to one hour ago, so a full pull must pass an
# explicit lower bound. Each full refresh re-pulls this trailing window (older events age out of the
# table). A future incremental mode could instead resume from the last `recorded_at` — see source.py.
AUDIT_TRAIL_LOOKBACK_DAYS = 90

# Consumptions take one `billing_period` per request and default to the current month, so a full refresh
# walks the current month plus the months before it.
BILLING_CONSUMPTION_LOOKBACK_MONTHS = 12


@dataclass  # nosemgrep: prefer-frozen-dataclasses -- pre-existing; new fields shift the backlog finding into diff
class ScalewayEndpointConfig:
    name: str
    # Path relative to the API base URL. May contain a `{region}` or `{zone}` placeholder that the
    # connector fills from the scope list before requesting.
    path: str
    # JSON key in the response body holding the array of rows.
    data_key: str
    pagination: Pagination
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-timestamp field used for datetime partitioning. Never a mutable "updated"/
    # "modified" field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    scope: Scope = "none"
    # Regions or zones the endpoint fans out over, for the "region", "zone" and "k8s_cluster" scopes.
    scope_values: list[str] = field(default_factory=list)
    # Query-param name used to scope the request to the connected organization. Scaleway is
    # inconsistent here: most products take `organization_id`, but Instance takes `organization`.
    # `None` means the endpoint isn't organization-scoped.
    org_param: Optional[str] = "organization_id"
    # Sort param name + value. Scaleway uses `order_by` on most products but `order` on Instance.
    # An explicit ascending sort keeps pagination stable across page boundaries. Values are taken
    # from the products' OpenAPI schemas.
    order_param: Optional[str] = None
    order_value: Optional[str] = None
    # Extra static query params merged into every request.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Server-side lower-bound time filter (e.g. Audit Trail's `recorded_after`). When set, the
    # connector passes `<lookback_param>=now-<lookback_days>` so a full refresh pulls a bounded
    # trailing window instead of relying on the endpoint's tiny default window.
    lookback_param: Optional[str] = None
    lookback_days: Optional[int] = None
    should_sync_default: bool = True
    description: Optional[str] = None


SCALEWAY_ENDPOINTS: dict[str, ScalewayEndpointConfig] = {
    "users": ScalewayEndpointConfig(
        name="users",
        path="/iam/v1alpha1/users",
        data_key="users",
        pagination="page_size",
        partition_key="created_at",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "applications": ScalewayEndpointConfig(
        name="applications",
        path="/iam/v1alpha1/applications",
        data_key="applications",
        pagination="page_size",
        partition_key="created_at",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "groups": ScalewayEndpointConfig(
        name="groups",
        path="/iam/v1alpha1/groups",
        data_key="groups",
        pagination="page_size",
        partition_key="created_at",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "policies": ScalewayEndpointConfig(
        name="policies",
        path="/iam/v1alpha1/policies",
        data_key="policies",
        pagination="page_size",
        partition_key="created_at",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "api_keys": ScalewayEndpointConfig(
        name="api_keys",
        path="/iam/v1alpha1/api-keys",
        data_key="api_keys",
        # API keys are identified by their public access key, not an `id`.
        primary_keys=["access_key"],
        pagination="page_size",
        partition_key="created_at",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "ssh_keys": ScalewayEndpointConfig(
        name="ssh_keys",
        path="/iam/v1alpha1/ssh-keys",
        data_key="ssh_keys",
        pagination="page_size",
        partition_key="created_at",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "projects": ScalewayEndpointConfig(
        name="projects",
        path="/account/v3/projects",
        data_key="projects",
        pagination="page_size",
        partition_key="created_at",
        # Account requires organization_id explicitly.
        org_param="organization_id",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "invoices": ScalewayEndpointConfig(
        name="invoices",
        path="/billing/v2beta1/invoices",
        data_key="invoices",
        pagination="page_size",
        # Invoices have no created_at/updated_at; start_date is the stable period start.
        partition_key="start_date",
        org_param="organization_id",
        order_param="order_by",
        order_value="start_date_asc",
    ),
    "instance_servers": ScalewayEndpointConfig(
        name="instance_servers",
        path="/instance/v1/zones/{zone}/servers",
        data_key="servers",
        pagination="per_page",
        # Instance uses `creation_date`/`modification_date` rather than `created_at`/`updated_at`.
        partition_key="creation_date",
        scope="zone",
        scope_values=INSTANCE_ZONES,
        org_param="organization",
        order_param="order",
        order_value="creation_date_asc",
    ),
    "audit_trail_events": ScalewayEndpointConfig(
        name="audit_trail_events",
        path="/audit-trail/v1alpha1/regions/{region}/events",
        data_key="events",
        pagination="token",
        partition_key="recorded_at",
        scope="region",
        scope_values=AUDIT_TRAIL_REGIONS,
        # Audit Trail requires organization_id explicitly.
        org_param="organization_id",
        order_param="order_by",
        order_value="recorded_at_asc",
        lookback_param="recorded_after",
        lookback_days=AUDIT_TRAIL_LOOKBACK_DAYS,
        description=(f"Syncs the most recent {AUDIT_TRAIL_LOOKBACK_DAYS} days of audit events on each full refresh"),
    ),
    "billing_consumptions": ScalewayEndpointConfig(
        name="billing_consumptions",
        path="/billing/v2beta1/consumptions",
        data_key="consumptions",
        pagination="page_size",
        # Consumption rows have no id or date of their own. The connector adds `billing_period` to each
        # row, and a row is one SKU of one resource in one project for that month.
        primary_keys=["billing_period", "project_id", "category_name", "sku", "resource_name"],
        scope="billing_period",
        org_param="organization_id",
        order_param="order_by",
        order_value="updated_at_asc",
        description=(
            f"Syncs consumption for the current and previous {BILLING_CONSUMPTION_LOOKBACK_MONTHS - 1} "
            "billing periods on each full refresh"
        ),
    ),
    "kubernetes_clusters": ScalewayEndpointConfig(
        name="kubernetes_clusters",
        path="/k8s/v1/regions/{region}/clusters",
        data_key="clusters",
        pagination="page_size",
        partition_key="created_at",
        scope="region",
        scope_values=K8S_REGIONS,
        org_param="organization_id",
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "kubernetes_pools": ScalewayEndpointConfig(
        name="kubernetes_pools",
        path="/k8s/v1/regions/{region}/clusters/{cluster_id}/pools",
        data_key="pools",
        pagination="page_size",
        partition_key="created_at",
        scope="k8s_cluster",
        scope_values=K8S_REGIONS,
        # The cluster in the path already scopes the request; this endpoint takes no organization filter.
        org_param=None,
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "kubernetes_nodes": ScalewayEndpointConfig(
        name="kubernetes_nodes",
        path="/k8s/v1/regions/{region}/clusters/{cluster_id}/nodes",
        data_key="nodes",
        pagination="page_size",
        partition_key="created_at",
        scope="k8s_cluster",
        scope_values=K8S_REGIONS,
        org_param=None,
        order_param="order_by",
        order_value="created_at_asc",
    ),
    "database_instances": ScalewayEndpointConfig(
        name="database_instances",
        path="/rdb/v1/regions/{region}/instances",
        data_key="instances",
        pagination="page_size",
        partition_key="created_at",
        scope="region",
        scope_values=RDB_REGIONS,
        org_param="organization_id",
        order_param="order_by",
        order_value="created_at_asc",
    ),
}

# The endpoint that lists the clusters the "k8s_cluster" scope fans out over.
K8S_CLUSTERS_ENDPOINT = "kubernetes_clusters"

ENDPOINTS = tuple(SCALEWAY_ENDPOINTS.keys())

# Every endpoint ships as full refresh: none of Scaleway's list endpoints expose a verified server-side
# "updated since" filter with a matching stable ascending sort, and the resource inventories are small.
# Kept as an explicit (empty) map so the shape matches the other sources and incremental fields can be
# added per endpoint once behavior is curl-verified against the live API.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
