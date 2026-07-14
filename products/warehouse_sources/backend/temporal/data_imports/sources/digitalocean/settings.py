from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# DigitalOcean caps `per_page` at 200; use the max to minimize round trips against the
# 5,000 req/hour + 250 req/minute rate limits.
PAGE_SIZE = 200


@dataclass
class DigitalOceanEndpointConfig:
    name: str
    # Path relative to the API root (https://api.digitalocean.com).
    path: str
    # Key the list of records is nested under in the JSON response body
    # (e.g. `{"droplets": [...]}` → "droplets").
    data_selector: str
    # Columns that uniquely identify a record table-wide. DigitalOcean resource ids are
    # globally unique; keyless resources (domains, tags) use their natural name/ip key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp to partition by. `None` for resources the API doesn't stamp
    # with a creation time. Never a mutable field like `updated_at`.
    partition_key: Optional[str] = None
    # Extra query params merged into every request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)


# DigitalOcean's list endpoints all share the same page-based pagination
# (`links.pages.next` full URLs, `meta.total`) and none expose a server-side
# `updated_since`/`created_since` filter, so every endpoint is full-refresh only.
DIGITALOCEAN_ENDPOINTS: dict[str, DigitalOceanEndpointConfig] = {
    "droplets": DigitalOceanEndpointConfig(
        name="droplets",
        path="/v2/droplets",
        data_selector="droplets",
        partition_key="created_at",
    ),
    "apps": DigitalOceanEndpointConfig(
        name="apps",
        path="/v2/apps",
        data_selector="apps",
        partition_key="created_at",
    ),
    "kubernetes_clusters": DigitalOceanEndpointConfig(
        name="kubernetes_clusters",
        path="/v2/kubernetes/clusters",
        data_selector="kubernetes_clusters",
        partition_key="created_at",
    ),
    "databases": DigitalOceanEndpointConfig(
        name="databases",
        path="/v2/databases",
        data_selector="databases",
        partition_key="created_at",
    ),
    "volumes": DigitalOceanEndpointConfig(
        name="volumes",
        path="/v2/volumes",
        data_selector="volumes",
        partition_key="created_at",
    ),
    "snapshots": DigitalOceanEndpointConfig(
        name="snapshots",
        path="/v2/snapshots",
        data_selector="snapshots",
        partition_key="created_at",
    ),
    "load_balancers": DigitalOceanEndpointConfig(
        name="load_balancers",
        path="/v2/load_balancers",
        data_selector="load_balancers",
        partition_key="created_at",
    ),
    "projects": DigitalOceanEndpointConfig(
        name="projects",
        path="/v2/projects",
        data_selector="projects",
        partition_key="created_at",
    ),
    "vpcs": DigitalOceanEndpointConfig(
        name="vpcs",
        path="/v2/vpcs",
        data_selector="vpcs",
        partition_key="created_at",
    ),
    # User-owned images only; the unfiltered list also returns every public distribution
    # and application image, which is huge and identical for every account.
    "images": DigitalOceanEndpointConfig(
        name="images",
        path="/v2/images",
        data_selector="images",
        partition_key="created_at",
        extra_params={"private": "true"},
    ),
    "domains": DigitalOceanEndpointConfig(
        name="domains",
        path="/v2/domains",
        data_selector="domains",
        primary_keys=["name"],
    ),
    "ssh_keys": DigitalOceanEndpointConfig(
        name="ssh_keys",
        path="/v2/account/keys",
        data_selector="ssh_keys",
    ),
    "reserved_ips": DigitalOceanEndpointConfig(
        name="reserved_ips",
        path="/v2/reserved_ips",
        data_selector="reserved_ips",
        primary_keys=["ip"],
    ),
    "tags": DigitalOceanEndpointConfig(
        name="tags",
        path="/v2/tags",
        data_selector="tags",
        primary_keys=["name"],
    ),
    "invoices": DigitalOceanEndpointConfig(
        name="invoices",
        path="/v2/customers/my/invoices",
        data_selector="invoices",
        primary_keys=["invoice_uuid"],
    ),
    # Append-only financial ledger with no natural unique key. The composite is a best-effort
    # dedup guard; the endpoint is full-refresh (replace) so it's rewritten wholesale each sync.
    "billing_history": DigitalOceanEndpointConfig(
        name="billing_history",
        path="/v2/customers/my/billing_history",
        data_selector="billing_history",
        primary_keys=["date", "type", "amount", "description"],
    ),
}

ENDPOINTS = tuple(DIGITALOCEAN_ENDPOINTS.keys())

# DigitalOcean exposes no server-side timestamp filter on any list endpoint, so no endpoint
# supports genuine incremental sync. Kept for parity with the schema-building convention.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
