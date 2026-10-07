from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class JobNimbusEndpointConfig:
    name: str
    path: str
    # JobNimbus records carry a globally unique `jnid` (not `id`), so it is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["jnid"])
    # None selects the whole body, for endpoints that return a bare JSON list.
    data_selector: str | None = "results"
    params: dict[str, str] = field(default_factory=dict)
    # Account lookups (users, settings) return the whole collection in one body with no `size`/`from`.
    paginated: bool = True


# JobNimbus Open API top-level list endpoints. All are full-refresh only: while records expose
# `date_created` / `date_updated` epoch fields, the server-side modification filter syntax isn't
# documented well enough to advance an incremental cursor safely, so a client-side scan would cost
# the same as a full refresh (see the implementing-warehouse-sources skill).
JOBNIMBUS_ENDPOINTS: dict[str, JobNimbusEndpointConfig] = {
    "contacts": JobNimbusEndpointConfig(name="contacts", path="/contacts"),
    "jobs": JobNimbusEndpointConfig(name="jobs", path="/jobs"),
    "tasks": JobNimbusEndpointConfig(name="tasks", path="/tasks"),
    "activities": JobNimbusEndpointConfig(name="activities", path="/activities"),
    "payments": JobNimbusEndpointConfig(name="payments", path="/payments"),
    "estimates": JobNimbusEndpointConfig(name="estimates", path="/v2/estimates"),
    "invoices": JobNimbusEndpointConfig(name="invoices", path="/v2/invoices"),
    "products": JobNimbusEndpointConfig(name="products", path="/v2/products"),
    "budgets": JobNimbusEndpointConfig(name="budgets", path="/budgets"),
    "users": JobNimbusEndpointConfig(
        name="users", path="/account/users", primary_keys=["id"], data_selector="users", paginated=False
    ),
    # Workflows (with their nested statuses) and lead sources both come from the account settings
    # document; each table selects one of its lookup lists.
    "workflows": JobNimbusEndpointConfig(
        name="workflows", path="/account/settings", primary_keys=["id"], data_selector="workflows", paginated=False
    ),
    "lead_sources": JobNimbusEndpointConfig(
        name="lead_sources",
        path="/account/settings",
        primary_keys=["JobSourceId"],
        data_selector="sources",
        paginated=False,
    ),
    # Groups carry no ID; JobNimbus identifies a group by its name.
    "groups": JobNimbusEndpointConfig(
        name="groups",
        path="/account/settings",
        params={"field": "groups"},
        primary_keys=["name"],
        data_selector=None,
        paginated=False,
    ),
}

ENDPOINTS = tuple(JOBNIMBUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
