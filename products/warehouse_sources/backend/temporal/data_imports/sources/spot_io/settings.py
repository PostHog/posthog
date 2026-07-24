from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

SPOT_IO_BASE_URL = "https://api.spotinst.io"

# The `costs/detailed` endpoint requires a fromDate/toDate window on every call and its rows
# carry no per-row timestamp we could track a real incremental watermark from (each row is one
# instance's totals over the whole window), so every sync re-pulls a fixed trailing window
# rather than advancing a cursor. 30 days keeps the response bounded while covering the typical
# billing-review horizon.
DEFAULT_COST_LOOKBACK_DAYS = 30


@dataclass
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
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None


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
}

# Fan-out children are synced directly (never the bare "elastigroups" parent table on its own
# as a schema choice alongside "elastigroup_costs" would double-count); "elastigroups" is still
# exposed as its own top-level table for users who only want the entity list.
ENDPOINTS = tuple(SPOT_IO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SPOT_IO_ENDPOINTS.items()
}
