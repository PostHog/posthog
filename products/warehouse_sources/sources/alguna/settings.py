from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, ResponseAction

# Alguna list endpoints paginate with limit/offset.
PAGE_LIMIT = 100

# Every stream is full refresh. Alguna's list endpoints expose no created_at/updated_at server-side
# filters, and while /invoices supports issue/paid/due/invoicing date-range filters, the invoice
# *list* payload (InvoiceListItemResponse) doesn't include those date fields — so the pipeline
# can't track a watermark from synced rows. Billing data is low-cardinality, so full refresh is fine.


@dataclass(frozen=True)
class AlgunaQueryFanout:
    # Fan-out where the parent id rides a required *query* param on the child list endpoint (e.g.
    # /credit-notes?customer_id=...). The shared rest_source fan-out only binds resolve params in
    # the *path*, so these route through a hand-rolled iterator in alguna.py instead.
    parent_name: str
    query_param: str
    parent_field: str = "id"


@dataclass(frozen=True)
class AlgunaEndpointConfig:
    name: str
    path: str
    # Alguna requires `sort` (format "field:order") on most list endpoints; None for the endpoints
    # that don't accept it (payments, products, wallets, wallet-grants). All entities carry
    # created_at, and the API docs use it in sort examples, so it's the stable pagination order for
    # the endpoints that sort.
    sort: str | None = "created_at:asc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # None for rows with no stable datetime (e.g. bundles, subscription revenue): no partitioning.
    partition_key: str | None = "created_at"
    # "$" for a child that returns one object per parent instead of a `data` list.
    data_selector: str = "data"
    # For a single-object response whose rows sit in a nested list (e.g. /revenue-schedules
    # `entries`): rows are read from this key and get the envelope's scalar fields copied in.
    rows_key: str | None = None
    # Fixed query params for an unpaginated endpoint.
    params: dict[str, Any] = field(default_factory=dict)
    # Whether the endpoint offset-paginates. False for a fan-out child that returns its whole
    # collection in one response (e.g. /subscriptions/{id}/versions).
    paginated: bool = True
    page_size: int = PAGE_LIMIT
    # Full refresh only — kept so the config satisfies the fan-out helper's protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Path-based fan-out driven by the shared rest_source helper (parent id in a {placeholder}).
    fanout: DependentEndpointConfig | None = None
    # Query-param fan-out driven by the hand-rolled iterator in alguna.py.
    query_fanout: AlgunaQueryFanout | None = None


# The per-subscription endpoints read the current version; a subscription without one returns
# no data for it, so a 404 means an empty child rather than a failed sync. The per-customer
# endpoints 404 for a customer deleted between the parent listing and the child fetch.
_IGNORE_CHILD_404: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]

ALGUNA_ENDPOINTS: dict[str, AlgunaEndpointConfig] = {
    "billable_metrics": AlgunaEndpointConfig(name="billable_metrics", path="/metrics"),
    "bundles": AlgunaEndpointConfig(name="bundles", path="/bundles", sort=None, partition_key=None),
    "credit_notes": AlgunaEndpointConfig(
        name="credit_notes",
        path="/credit-notes",
        sort=None,
        # /credit-notes requires a customer_id query param, so list per customer.
        query_fanout=AlgunaQueryFanout(parent_name="customers", query_param="customer_id"),
    ),
    "customers": AlgunaEndpointConfig(name="customers", path="/customers"),
    "customer_connected_accounts": AlgunaEndpointConfig(
        name="customer_connected_accounts",
        path="/customers/{customer_id}/connected-accounts",
        sort=None,
        primary_keys=["customer_id", "id"],
        partition_key=None,
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="customers",
            resolve_param="customer_id",
            resolve_field="id",
            # The connected-account payload already carries customer_id.
            include_from_parent=[],
            child_response_actions=_IGNORE_CHILD_404,
        ),
    ),
    "customer_entitlements": AlgunaEndpointConfig(
        name="customer_entitlements",
        path="/customers/{customer_id}/entitlements",
        sort=None,
        # Entitlements have no id. A key is unique within the subscription that grants it;
        # subscription_id is null for default-profile entitlements. Full refresh only, so the key
        # is never used to merge.
        primary_keys=["customer_id", "subscription_id", "key"],
        partition_key=None,
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="customers",
            resolve_param="customer_id",
            resolve_field="id",
            # The entitlement payload carries no customer id, so copy it down from the parent.
            include_from_parent=["id"],
            parent_field_renames={"id": "customer_id"},
            child_response_actions=_IGNORE_CHILD_404,
        ),
    ),
    "invoices": AlgunaEndpointConfig(name="invoices", path="/invoices"),
    "payments": AlgunaEndpointConfig(name="payments", path="/payments", sort=None),
    "plans": AlgunaEndpointConfig(name="plans", path="/plans"),
    "products": AlgunaEndpointConfig(name="products", path="/products", sort=None),
    "refunds": AlgunaEndpointConfig(name="refunds", path="/refunds"),
    "revenue_schedule": AlgunaEndpointConfig(
        name="revenue_schedule",
        path="/revenue-schedules",
        sort=None,
        # One entry per interval in a single organization-wide response.
        primary_keys=["start_date"],
        partition_key="start_date",
        paginated=False,
        rows_key="entries",
        # The interval sets the table grain; pin it rather than rely on the API default.
        params={"interval": "monthly"},
    ),
    "subscriptions": AlgunaEndpointConfig(name="subscriptions", path="/subscriptions"),
    "subscription_revenue": AlgunaEndpointConfig(
        name="subscription_revenue",
        path="/subscriptions/{subscription_id}/revenue",
        sort=None,
        primary_keys=["subscription_id"],
        partition_key=None,
        paginated=False,
        data_selector="$",
        fanout=DependentEndpointConfig(
            parent_name="subscriptions",
            resolve_param="subscription_id",
            resolve_field="id",
            # The revenue payload already carries subscription_id; nothing to copy down.
            include_from_parent=[],
            child_response_actions=_IGNORE_CHILD_404,
        ),
    ),
    "subscription_versions": AlgunaEndpointConfig(
        name="subscription_versions",
        path="/subscriptions/{subscription_id}/versions",
        sort=None,
        # Version id is unique within its subscription; scope it with the parent to be safe.
        primary_keys=["subscription_id", "id"],
        # The versions endpoint returns the whole list in one response — no limit/offset.
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="subscriptions",
            resolve_param="subscription_id",
            resolve_field="id",
            # The version payload already carries subscription_id; nothing to copy down.
            include_from_parent=[],
        ),
    ),
    "wallets": AlgunaEndpointConfig(name="wallets", path="/wallets", sort=None),
    "wallet_grants": AlgunaEndpointConfig(name="wallet_grants", path="/wallet-grants", sort=None),
}

ENDPOINTS = tuple(ALGUNA_ENDPOINTS.keys())

# Empty: no endpoint exposes an incremental watermark (see the note above), so every stream is full
# refresh. `build_endpoint_schemas` treats a missing entry — not an empty list — as non-incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
