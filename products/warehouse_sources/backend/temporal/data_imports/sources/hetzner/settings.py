from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class HetznerEndpointConfig:
    name: str
    path: str
    # JSON envelope key the list lives under, e.g. {"servers": [...], "meta": {...}}.
    response_key: str
    # Stable, immutable datetime field to partition by (never a mutable `updated`-style field).
    # None for the pricing-catalog endpoints, which carry no timestamps.
    partition_key: Optional[str] = None
    # Value passed to the API's `sort` param (Hetzner format, e.g. "id:asc"). Sorting a stable
    # monotonic column ascending keeps new rows appending to the end so a full-refresh sync can't
    # skip or duplicate rows across page boundaries. None leaves the endpoint at its default order
    # (used for the small catalog endpoints, whose sort support we could not curl-verify).
    sort: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# The Hetzner Cloud API exposes no server-side timestamp filter on any list endpoint (no
# `created_since` / `updated_after` / `id_gt`), so every table is full refresh only — there is no
# cursor that would make an "incremental" sync cheaper than re-reading every page. Actions are
# append-only and immutable, but without a server filter they too must be full refreshed. Sorting
# by `id:asc` gives a stable ascending order so pagination stays consistent while a full refresh runs.
HETZNER_ENDPOINTS: dict[str, HetznerEndpointConfig] = {
    "servers": HetznerEndpointConfig(
        name="servers",
        path="/servers",
        response_key="servers",
        partition_key="created",
        sort="id:asc",
    ),
    "volumes": HetznerEndpointConfig(
        name="volumes",
        path="/volumes",
        response_key="volumes",
        partition_key="created",
        sort="id:asc",
    ),
    "load_balancers": HetznerEndpointConfig(
        name="load_balancers",
        path="/load_balancers",
        response_key="load_balancers",
        partition_key="created",
        sort="id:asc",
    ),
    "networks": HetznerEndpointConfig(
        name="networks",
        path="/networks",
        response_key="networks",
        partition_key="created",
        sort="id:asc",
    ),
    "firewalls": HetznerEndpointConfig(
        name="firewalls",
        path="/firewalls",
        response_key="firewalls",
        partition_key="created",
        sort="id:asc",
    ),
    "images": HetznerEndpointConfig(
        name="images",
        path="/images",
        response_key="images",
        partition_key="created",
        sort="id:asc",
    ),
    "floating_ips": HetznerEndpointConfig(
        name="floating_ips",
        path="/floating_ips",
        response_key="floating_ips",
        partition_key="created",
        sort="id:asc",
    ),
    "primary_ips": HetznerEndpointConfig(
        name="primary_ips",
        path="/primary_ips",
        response_key="primary_ips",
        partition_key="created",
        sort="id:asc",
    ),
    "certificates": HetznerEndpointConfig(
        name="certificates",
        path="/certificates",
        response_key="certificates",
        partition_key="created",
        sort="id:asc",
    ),
    "ssh_keys": HetznerEndpointConfig(
        name="ssh_keys",
        path="/ssh_keys",
        response_key="ssh_keys",
        partition_key="created",
        sort="id:asc",
    ),
    "placement_groups": HetznerEndpointConfig(
        name="placement_groups",
        path="/placement_groups",
        response_key="placement_groups",
        partition_key="created",
        sort="id:asc",
    ),
    # Append-only audit history of every operation. No `created` field, so no datetime partition;
    # `id` is monotonic, so sort ascending for stable pagination.
    "actions": HetznerEndpointConfig(
        name="actions",
        path="/actions",
        response_key="actions",
        sort="id:asc",
    ),
    # Pricing / infrastructure catalog. Same for every project, no timestamps, small enough to fit a
    # page or two, so no partitioning and no explicit sort.
    "server_types": HetznerEndpointConfig(
        name="server_types",
        path="/server_types",
        response_key="server_types",
    ),
    "load_balancer_types": HetznerEndpointConfig(
        name="load_balancer_types",
        path="/load_balancer_types",
        response_key="load_balancer_types",
    ),
    "datacenters": HetznerEndpointConfig(
        name="datacenters",
        path="/datacenters",
        response_key="datacenters",
    ),
    "locations": HetznerEndpointConfig(
        name="locations",
        path="/locations",
        response_key="locations",
    ),
    "isos": HetznerEndpointConfig(
        name="isos",
        path="/isos",
        response_key="isos",
    ),
}

ENDPOINTS = tuple(HETZNER_ENDPOINTS.keys())

# Hetzner has no server-side timestamp filter, so no endpoint advertises incremental fields. Kept
# for parity with the other sources and so `get_schemas` can read a single source of truth.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in HETZNER_ENDPOINTS}
