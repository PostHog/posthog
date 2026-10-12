from dataclasses import dataclass, field


@dataclass
class VultrEndpointConfig:
    name: str
    # API path, appended to the Vultr base URL (https://api.vultr.com).
    path: str
    # JSONPath to the row array in the response body (e.g. "instances", "vke_clusters").
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


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
}
