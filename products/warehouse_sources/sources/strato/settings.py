from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

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


@frozen
class StratoEndpointConfig:
    name: str
    path: str
    # Every STRATO resource carries an ISO-8601 `creation_date`, which never changes after create.
    partition_key: str | None = "creation_date"
    primary_key: str | list[str] = "id"
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
}

ENDPOINTS = tuple(STRATO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STRATO_ENDPOINTS.items()
}
