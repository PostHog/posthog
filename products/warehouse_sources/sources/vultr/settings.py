from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

# Vultr caps per_page at 500 (default 100). Fewer requests keeps us well under the ~30 req/s rate limit.
VULTR_PER_PAGE = 500


@dataclass
class VultrEndpointConfig:
    name: str
    # API path, appended to the Vultr base URL (https://api.vultr.com).
    path: str
    # JSONPath to the row array in the response body (e.g. "instances", "vke_clusters").
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Extra documented query params sent on every request to this endpoint.
    params: dict[str, Any] = field(default_factory=dict)
    # False for an endpoint that returns its whole result in one response, with no `meta` cursor.
    paginated: bool = True
    # Path fan-out from a parent endpoint (the parent id fills the `{placeholder}` in `path`).
    fanout: DependentEndpointConfig | None = None
    page_size: int = VULTR_PER_PAGE
    # Full refresh only. Kept so the config satisfies the fan-out helper's protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


# Vultr API v2 has no server-side updated-since / created-since filter and no webhooks on any list
# endpoint, so every endpoint is full-refresh (write_disposition="replace"). Per-account entity counts
# are small, so a full pull per run is fine. See the source-local api_inventory.md for the survey notes.
ENDPOINTS: dict[str, VultrEndpointConfig] = {
    "instances": VultrEndpointConfig(name="instances", path="/v2/instances", data_selector="instances"),
    "bare_metals": VultrEndpointConfig(name="bare_metals", path="/v2/bare-metals", data_selector="bare_metals"),
    "kubernetes_clusters": VultrEndpointConfig(
        name="kubernetes_clusters", path="/v2/kubernetes/clusters", data_selector="vke_clusters"
    ),
    "block_storage": VultrEndpointConfig(name="block_storage", path="/v2/blocks", data_selector="blocks"),
    "snapshots": VultrEndpointConfig(name="snapshots", path="/v2/snapshots", data_selector="snapshots"),
    "load_balancers": VultrEndpointConfig(
        name="load_balancers", path="/v2/load-balancers", data_selector="load_balancers"
    ),
    "managed_databases": VultrEndpointConfig(name="managed_databases", path="/v2/databases", data_selector="databases"),
    "users": VultrEndpointConfig(name="users", path="/v2/users", data_selector="users"),
    "billing_history": VultrEndpointConfig(
        name="billing_history", path="/v2/billing/history", data_selector="billing_history"
    ),
    "invoices": VultrEndpointConfig(name="invoices", path="/v2/billing/invoices", data_selector="billing_invoices"),
    # Line items carry no id of their own. `vultr.py` numbers them per invoice in response order.
    "invoice_items": VultrEndpointConfig(
        name="invoice_items",
        path="/v2/billing/invoices/{invoice_id}/items",
        data_selector="invoice_items",
        primary_keys=["invoice_id", "line_number"],
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoice_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "invoice_id"},
        ),
    ),
    # The API returns one object keyed by UTC date, for a rolling window of recent days only.
    # `vultr.py` turns each date into a row.
    "instance_bandwidth": VultrEndpointConfig(
        name="instance_bandwidth",
        path="/v2/instances/{instance_id}/bandwidth",
        data_selector="bandwidth",
        primary_keys=["instance_id", "date"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="instances",
            resolve_param="instance_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "instance_id"},
            # An instance destroyed between the instance listing and its bandwidth fetch 404s.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "regions": VultrEndpointConfig(name="regions", path="/v2/regions", data_selector="regions"),
    # `type=all` is the documented filter value that lists every non-bare-metal plan type.
    "plans": VultrEndpointConfig(name="plans", path="/v2/plans", data_selector="plans", params={"type": "all"}),
    # The OpenAPI schema names the array `plans`, but its example and the govultr client use `plans_metal`.
    "bare_metal_plans": VultrEndpointConfig(
        name="bare_metal_plans", path="/v2/plans-metal", data_selector="plans_metal"
    ),
}
