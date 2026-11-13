from dataclasses import field
from typing import Any

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen

STRATO_BASE_URL = "https://scp-api.strato.de/v1"

# Snapshots only exist per server (/servers/{server_id}/snapshots); Servers is the parent list
# the endpoint fans out from. A server deleted between the parent listing and the child fetch
# returns 404, which must not fail the whole sync.
SERVER_SNAPSHOTS_FANOUT = DependentEndpointConfig(
    parent_name="Servers",
    resolve_param="server_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "server_id"},
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

# `period` is required by /usages and /monitoring_center/{server_id}. The longest preset is used
# for usages, because it is one request per sync and each resource's `detail` list breaks the
# window into the intervals where its usage changed. Monitoring returns raw samples per server,
# so it uses a shorter window to keep each response small.
USAGES_PERIOD = "LAST_365D"
SERVER_MONITORING_PERIOD = "LAST_30D"

SERVER_MONITORING_FANOUT = DependentEndpointConfig(
    parent_name="Servers",
    resolve_param="server_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "server_id"},
    child_params={"period": SERVER_MONITORING_PERIOD},
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


@frozen
class StratoEndpointConfig:
    name: str
    path: str
    # Every STRATO resource carries an ISO-8601 `creation_date`, which never changes after create.
    # Catalogs and reports have no such field and set this to None.
    partition_key: str | None = "creation_date"
    primary_key: str | list[str] = "id"
    params: dict[str, Any] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Unused: STRATO list endpoints return the whole collection, so no page-size param is sent
    # (page_size_param=None everywhere). Kept to satisfy the fan-out builder's endpoint protocol.
    page_size: int = 100
    fanout: DependentEndpointConfig | None = None


# The STRATO Cloud Server API documents `page`/`per_page` params, but collections are small and
# returned whole when the params are omitted, and the API exposes no server-side timestamp filter
# (only `sort` and free-text `q`), so every endpoint is an unpaginated full refresh.
STRATO_ENDPOINTS: dict[str, StratoEndpointConfig] = {
    "Servers": StratoEndpointConfig(name="Servers", path="/servers"),
    "Snapshots": StratoEndpointConfig(
        name="Snapshots",
        path="/servers/{server_id}/snapshots",
        # Snapshot ids are only documented as unique per server, so the parent id is part of the key.
        primary_key=["server_id", "id"],
        fanout=SERVER_SNAPSHOTS_FANOUT,
    ),
    "Images": StratoEndpointConfig(name="Images", path="/images"),
    "BlockStorages": StratoEndpointConfig(name="BlockStorages", path="/block_storages"),
    "SharedStorages": StratoEndpointConfig(name="SharedStorages", path="/shared_storages"),
    "FirewallPolicies": StratoEndpointConfig(name="FirewallPolicies", path="/firewall_policies"),
    "LoadBalancers": StratoEndpointConfig(name="LoadBalancers", path="/load_balancers"),
    "PublicIps": StratoEndpointConfig(name="PublicIps", path="/public_ips"),
    "PrivateNetworks": StratoEndpointConfig(name="PrivateNetworks", path="/private_networks"),
    "Vpns": StratoEndpointConfig(name="Vpns", path="/vpns"),
    "MonitoringPolicies": StratoEndpointConfig(name="MonitoringPolicies", path="/monitoring_policies"),
    "SshKeys": StratoEndpointConfig(name="SshKeys", path="/ssh_keys"),
    "Users": StratoEndpointConfig(name="Users", path="/users"),
    "Roles": StratoEndpointConfig(name="Roles", path="/roles"),
    "FixedInstanceSizes": StratoEndpointConfig(
        name="FixedInstanceSizes", path="/servers/fixed_instance_sizes", partition_key=None
    ),
    "BaremetalModels": StratoEndpointConfig(
        name="BaremetalModels", path="/servers/baremetal_models", partition_key=None
    ),
    # /usages returns one object keyed by resource type (SERVERS, IMAGES, ...). It is flattened to
    # one row per resource. Shared storages and public IPs carry no `id`, so `resource_key` falls
    # back to the name.
    "Usages": StratoEndpointConfig(
        name="Usages",
        path="/usages",
        partition_key=None,
        primary_key=["resource_type", "resource_key"],
        params={"period": USAGES_PERIOD},
    ),
    "ServerMonitoring": StratoEndpointConfig(
        name="ServerMonitoring",
        path="/monitoring_center/{server_id}",
        partition_key=None,
        primary_key="server_id",
        fanout=SERVER_MONITORING_FANOUT,
    ),
}

ENDPOINTS = tuple(STRATO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STRATO_ENDPOINTS.items()
}
