from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, incremental_field

SPOT_IO_BASE_URL = "https://api.spotinst.io"

# The `costs/detailed` endpoint requires a fromDate/toDate window on every call and its rows
# carry no per-row timestamp we could track a real incremental watermark from (each row is one
# instance's totals over the whole window), so every sync re-pulls a fixed trailing window
# rather than advancing a cursor. 30 days keeps the response bounded while covering the typical
# billing-review horizon.
DEFAULT_COST_LOOKBACK_DAYS = 30

# The activity events endpoint requires `fromDate`. A full refresh, and the first incremental
# sync, read this trailing window; later incremental syncs start from the watermark's date.
DEFAULT_EVENTS_LOOKBACK_DAYS = 90


@dataclass(frozen=False)
class SpotIoEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    # Unused: every endpoint here is either a single unpaginated response or a fan-out with no
    # page-size param, so callers always pass page_size_param=None. Kept only to satisfy the
    # shared fan-out helper's protocol.
    page_size: int = 0
    sort_mode: Literal["asc", "desc"] | None = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None
    # Organization-level endpoints list every account, so they never take the `accountId` filter.
    account_scoped: bool = True


SPOT_IO_ENDPOINTS: dict[str, SpotIoEndpointConfig] = {
    # AWS Elastigroups: spot/on-demand VM fleet definitions. No pagination params documented
    # and no server-side timestamp filter, so this is a small full-refresh entity list that the
    # cost fan-out below resolves `groupId` from.
    "elastigroups": SpotIoEndpointConfig(
        name="elastigroups",
        path="/aws/ec2/group",
        partition_key="createdAt",
        primary_key="id",
    ),
    # Ocean (Kubernetes) cluster configurations. Same full-refresh shape as elastigroups.
    "ocean_clusters": SpotIoEndpointConfig(
        name="ocean_clusters",
        path="/ocean/aws/k8s/cluster",
        partition_key="createdAt",
        primary_key="id",
    ),
    # Stateful Nodes (persistent single-instance workloads). Same full-refresh shape.
    "stateful_nodes": SpotIoEndpointConfig(
        name="stateful_nodes",
        path="/aws/ec2/managedInstance",
        partition_key="createdAt",
        primary_key="id",
    ),
    # Per-instance realized cost/savings for a rolling window, fanned out per elastigroup. The
    # API already returns `groupId` on every row, so no parent field injection is required for
    # identity — only the elastigroup name is pulled in for readability.
    "elastigroup_costs": SpotIoEndpointConfig(
        name="elastigroup_costs",
        path="/aws/ec2/group/{groupId}/costs/detailed",
        primary_key=["groupId", "instanceId"],
        fanout=DependentEndpointConfig(
            parent_name="elastigroups",
            resolve_param="groupId",
            resolve_field="id",
            include_from_parent=["name"],
            parent_field_renames={"name": "elastigroup_name"},
        ),
    ),
    # Scaling, spot interruption and update history per elastigroup. Rows have no id, so the
    # transport adds `event_key`, a hash of the event content. `fromDate` filters on `createdAt`
    # server-side, which makes incremental sync possible. Rows arrive per group, so the order
    # across the table is not known.
    "elastigroup_events": SpotIoEndpointConfig(
        name="elastigroup_events",
        path="/aws/ec2/group/{groupId}/events",
        incremental_fields=[incremental_field("createdAt")],
        default_incremental_field="createdAt",
        partition_key="createdAt",
        sort_mode=None,
        primary_key=["groupId", "event_key"],
        fanout=DependentEndpointConfig(
            parent_name="elastigroups",
            resolve_param="groupId",
            resolve_field="id",
            include_from_parent=["name"],
            parent_field_renames={"name": "elastigroup_name"},
        ),
    ),
    # The organization's Spot accounts, the lookup for the `accountId` on other rows. Listing all
    # accounts needs an Organization Admin token.
    "accounts": SpotIoEndpointConfig(
        name="accounts",
        path="/setup/account",
        primary_key="accountId",
        account_scoped=False,
    ),
    # Current nodes of each Ocean AWS cluster. Node rows do not carry their cluster id, so it is
    # injected from the parent.
    "ocean_cluster_nodes": SpotIoEndpointConfig(
        name="ocean_cluster_nodes",
        path="/ocean/aws/k8s/cluster/{oceanClusterId}/nodes",
        partition_key="createdAt",
        primary_key=["ocean_cluster_id", "instanceId"],
        fanout=DependentEndpointConfig(
            parent_name="ocean_clusters",
            resolve_param="oceanClusterId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "ocean_cluster_id"},
        ),
    ),
}

# Fan-out children are synced directly (never the bare "elastigroups" parent table on its own
# as a schema choice alongside "elastigroup_costs" would double-count); "elastigroups" is still
# exposed as its own top-level table for users who only want the entity list.
ENDPOINTS = tuple(SPOT_IO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SPOT_IO_ENDPOINTS.items()
}
