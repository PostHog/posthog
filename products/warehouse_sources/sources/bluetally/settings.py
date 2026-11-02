from dataclasses import field

from posthog.dataclasses import frozen


@frozen
class BluetallyEndpointConfig:
    path: str
    # BlueTally IDs are globally unique integers per resource, so `id` alone is a safe key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning (never `updated_at`, which churns).
    partition_key: str | None = "created_at"
    # Column to sort by while paginating. Every paginated list endpoint accepts `created_at`; sorting
    # on it ascending keeps offset pagination stable even as new rows are appended mid-sync. `None`
    # for endpoints that take no parameters at all.
    sort: str | None = "created_at"
    # JSONPath to the row array. `None` means the response body is the array itself.
    data_selector: str | None = None
    # Whether the endpoint accepts `limit`/`offset`.
    paginated: bool = True
    # Whether the endpoint accepts the `tenant_id` scoping parameter.
    accepts_tenant_id: bool = True


# IT-asset-management resources exposed by BlueTally's REST API. Except where a config below says
# otherwise, each is a plain `GET /<resource>` list endpoint returning a bare JSON array with
# limit/offset pagination, an integer `id`, and `created_at`/`updated_at` timestamps. The API has no
# server-side `updated_after`-style filter, so all of these sync as full refresh (see
# source.py / get_schemas).
BLUETALLY_ENDPOINTS: dict[str, BluetallyEndpointConfig] = {
    "assets": BluetallyEndpointConfig(path="/assets"),
    "accessories": BluetallyEndpointConfig(path="/accessories"),
    "components": BluetallyEndpointConfig(path="/components"),
    "consumables": BluetallyEndpointConfig(path="/consumables"),
    "licenses": BluetallyEndpointConfig(path="/licenses"),
    "employees": BluetallyEndpointConfig(path="/employees"),
    "products": BluetallyEndpointConfig(path="/products"),
    "categories": BluetallyEndpointConfig(path="/categories"),
    "manufacturers": BluetallyEndpointConfig(path="/manufacturers"),
    "suppliers": BluetallyEndpointConfig(path="/suppliers"),
    "locations": BluetallyEndpointConfig(path="/locations"),
    "departments": BluetallyEndpointConfig(path="/departments"),
    "statuses": BluetallyEndpointConfig(path="/statuses"),
    "depreciations": BluetallyEndpointConfig(path="/depreciations"),
    "maintenances": BluetallyEndpointConfig(path="/maintenances"),
    "audits": BluetallyEndpointConfig(path="/audits"),
    # The activity log carries no identifier for the log line itself — `item_id` and `user_id` point
    # at the affected resource and the actor — so the key is the composite that pins one entry, and
    # `timestamp` is the only temporal column it returns.
    "activity": BluetallyEndpointConfig(
        path="/activity",
        primary_keys=["timestamp", "type", "event", "item_id", "user_id"],
        partition_key="timestamp",
    ),
    # `/tenants` documents no parameters and wraps its rows in a `tenants` key. It returns one row
    # per tenant the API key can act on, with no timestamps to partition or sort on.
    "tenants": BluetallyEndpointConfig(
        path="/tenants",
        primary_keys=["tenant_id"],
        partition_key=None,
        sort=None,
        data_selector="tenants",
        paginated=False,
        accepts_tenant_id=False,
    ),
}

ENDPOINTS = tuple(BLUETALLY_ENDPOINTS.keys())
