from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

ORGANIZATION_ENDPOINT = "organization"
REGIONS_ENDPOINT = "regions"
WORKSPACE_GROUPS_ENDPOINT = "workspace_groups"
WORKSPACES_ENDPOINT = "workspaces"
BILLING_USAGE_ENDPOINT = "billing_usage"
PROJECTS_ENDPOINT = "projects"
STARTER_CLUSTERS_ENDPOINT = "starter_clusters"
AUDIT_LOGS_ENDPOINT = "audit_logs"

# Bounds how far back the first `billing_usage` sync (or any full-refresh run) reaches. The
# Management API requires an explicit startTime/endTime window on every call; this isn't a claim
# about how far back SingleStore retains usage history.
BILLING_USAGE_DEFAULT_LOOKBACK_DAYS = 30

# `aggregateBy` value sent on every billing/usage request (hour|day|month, per the Management
# API). Day keeps row counts small for a management-API-sized dataset while still catching
# day-to-day cost swings.
BILLING_USAGE_AGGREGATE_BY = "day"


@dataclass(frozen=True)
class SinglestoreEndpointConfig:
    name: str
    # Path appended to the versioned base URL (https://api.singlestore.com/{api_version}).
    path: str
    primary_keys: list[str]
    # Newer resources are only published under /v2; the original tables keep their /v1 paths.
    api_version: str = "v1"
    # True when the response body is a single JSON object rather than an array
    # (`organizations/current`) — the row list is that one object.
    is_single_object: bool = False
    # Must be a STABLE datetime field (never `updated_at`/a mutable status) so partitions don't
    # rewrite on every sync.
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


SINGLESTORE_ENDPOINTS: dict[str, SinglestoreEndpointConfig] = {
    # GET /v1/organizations/current -> a single Organization object (orgID, name, firewallRanges).
    ORGANIZATION_ENDPOINT: SinglestoreEndpointConfig(
        name=ORGANIZATION_ENDPOINT,
        path="organizations/current",
        primary_keys=["orgID"],
        is_single_object=True,
    ),
    # GET /v1/regions -> raw array of Region objects (regionID, region, provider, regionName).
    # No documented pagination or filter — full refresh.
    REGIONS_ENDPOINT: SinglestoreEndpointConfig(
        name=REGIONS_ENDPOINT,
        path="regions",
        primary_keys=["regionID"],
    ),
    # GET /v1/workspaceGroups -> raw array of WorkspaceGroup objects. No updated/created-since
    # filter is documented, so this is full refresh.
    WORKSPACE_GROUPS_ENDPOINT: SinglestoreEndpointConfig(
        name=WORKSPACE_GROUPS_ENDPOINT,
        path="workspaceGroups",
        primary_keys=["workspaceGroupID"],
        partition_key="createdAt",
    ),
    # GET /v1/workspaces?workspaceGroupID={id} -> raw array of Workspace objects. There is no
    # top-level workspace listing, so this is fanned out over every workspace group id. `state`
    # (suspended/resumed/resizing) has no time filter, so this is full refresh.
    WORKSPACES_ENDPOINT: SinglestoreEndpointConfig(
        name=WORKSPACES_ENDPOINT,
        path="workspaces",
        primary_keys=["workspaceID"],
        partition_key="createdAt",
    ),
    # GET /v1/billing/usage?startTime&endTime&aggregateBy -> {"billingUsage": [{"metric",
    # "description", "usage": [{startTime, endTime, ownerID/ownerId, resourceID/resourceId,
    # resourceName, resourceType, value}]}]}. The only endpoint with a server-side time filter, so
    # it's the one incremental stream; everything else above is a small, full-refresh dimension.
    BILLING_USAGE_ENDPOINT: SinglestoreEndpointConfig(
        name=BILLING_USAGE_ENDPOINT,
        path="billing/usage",
        primary_keys=["metric", "resourceName", "startTime"],
        partition_key="startTime",
        incremental_fields=[
            {
                "label": "startTime",
                "type": IncrementalFieldType.DateTime,
                "field": "startTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # GET /v2/projects -> raw array of Project objects (projectID, name, edition, createdAt). No
    # pagination or filter is documented, so this is full refresh.
    PROJECTS_ENDPOINT: SinglestoreEndpointConfig(
        name=PROJECTS_ENDPOINT,
        path="projects",
        primary_keys=["projectID"],
        api_version="v2",
        partition_key="createdAt",
    ),
    # GET /v2/sharedtier/virtualClusters -> raw array of Shared Edition (starter) clusters. These
    # are not in the workspace inventory. The objects carry no timestamp, so there is no partition.
    STARTER_CLUSTERS_ENDPOINT: SinglestoreEndpointConfig(
        name=STARTER_CLUSTERS_ENDPOINT,
        path="sharedtier/virtualClusters",
        primary_keys=["virtualClusterID"],
        api_version="v2",
    ),
    # GET /v2/auditLogs?startDate&nextToken -> {"auditLogs": [...], "nextToken": "..."}. `startDate`
    # is an inclusive RFC3339 lower bound on `createdAt`, so this is the incremental stream.
    AUDIT_LOGS_ENDPOINT: SinglestoreEndpointConfig(
        name=AUDIT_LOGS_ENDPOINT,
        path="auditLogs",
        primary_keys=["auditID"],
        api_version="v2",
        partition_key="createdAt",
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(SINGLESTORE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SINGLESTORE_ENDPOINTS.items()
}
