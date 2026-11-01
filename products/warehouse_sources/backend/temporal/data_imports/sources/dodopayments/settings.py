from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Dodo Payments serves test and live data from two entirely separate hosts, each with its own
# API key. A key issued for one mode is rejected by the other, so the mode is an explicit source
# field rather than something we can infer from the key.
MODE_HOSTS = {
    "live": "https://live.dodopayments.com",
    "test": "https://test.dodopayments.com",
}
DEFAULT_MODE = "live"

# Every list endpoint caps `page_size` at 100 (the default is 10).
PAGE_SIZE = 100

# `(connect, read)` seconds. Bounds every REST request so a stalled connect or a hung read cannot
# pin an import worker indefinitely; the read budget is generous because a slow page is still worth
# waiting for against the 240 requests/minute rate limit.
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)

# A parent row deleted between the parent listing and its child request returns 404 (the
# documented "not found" answer of every child endpoint). Skip that parent rather than fail the
# whole table.
SKIP_MISSING_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]

# Rows whose fields get restated after creation re-read a trailing 30 day window on every
# incremental run. Dodo only filters on `created_at` - there is no updated-since filter anywhere
# in the API - so a bare creation cursor would freeze `status`, `dispute_status` and
# `refund_status` at whatever they were when the row was first imported. Users can change the
# window per table in the schema settings.
RESTATED_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class DodoPaymentsEndpointConfig:
    path: str
    primary_keys: list[str]
    # Query param carrying the server-side "created on or after" filter, when the endpoint has
    # one. `None` means the endpoint offers no date filter at all and must be full-refreshed,
    # unless its fan-out parent has one.
    start_param: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. `None` where the resource has no
    # creation timestamp at all (brands).
    partition_key: str | None = "created_at"
    # `/brands` is the one list endpoint that takes no query parameters, so it is a single page.
    paginated: bool = True
    # Fields on these resources are restated in place after creation, so incremental runs need
    # the trailing re-read window above.
    restated: bool = False
    # Per-parent child endpoints, read once for each row of the parent listing.
    fanout: DependentEndpointConfig | None = None
    # Path params bound from the same parent row beside `fanout.resolve_param`, mapped to the
    # parent field each one reads.
    extra_resolve_fields: dict[str, str] = field(default_factory=dict)


DODOPAYMENTS_ENDPOINTS: dict[str, DodoPaymentsEndpointConfig] = {
    "payments": DodoPaymentsEndpointConfig(
        path="/payments",
        primary_keys=["payment_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "subscriptions": DodoPaymentsEndpointConfig(
        path="/subscriptions",
        primary_keys=["subscription_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "customers": DodoPaymentsEndpointConfig(
        path="/customers",
        primary_keys=["customer_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "refunds": DodoPaymentsEndpointConfig(
        path="/refunds",
        primary_keys=["refund_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "disputes": DodoPaymentsEndpointConfig(
        path="/disputes",
        primary_keys=["dispute_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "payouts": DodoPaymentsEndpointConfig(
        path="/payouts",
        primary_keys=["payout_id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "license_keys": DodoPaymentsEndpointConfig(
        path="/license_keys",
        primary_keys=["id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
        restated=True,
    ),
    "balance_ledger_entries": DodoPaymentsEndpointConfig(
        path="/balances/ledger",
        primary_keys=["id"],
        start_param="created_at_gte",
        incremental_fields=[incremental_field("created_at")],
    ),
    # Usage-billing events are immutable once ingested, and the filter param is `start`, not
    # `created_at_gte`.
    "events": DodoPaymentsEndpointConfig(
        path="/events",
        primary_keys=["event_id"],
        start_param="start",
        incremental_fields=[incremental_field("timestamp")],
        partition_key="timestamp",
    ),
    # Catalog resources: no date filter of any kind, so full refresh only.
    "products": DodoPaymentsEndpointConfig(path="/products", primary_keys=["product_id"]),
    "product_collections": DodoPaymentsEndpointConfig(path="/product-collections", primary_keys=["id"]),
    "discounts": DodoPaymentsEndpointConfig(path="/discounts", primary_keys=["discount_id"]),
    "addons": DodoPaymentsEndpointConfig(path="/addons", primary_keys=["id"]),
    "brands": DodoPaymentsEndpointConfig(
        path="/brands",
        primary_keys=["brand_id"],
        partition_key=None,
        paginated=False,
    ),
    "meters": DodoPaymentsEndpointConfig(path="/meters", primary_keys=["id"]),
    "license_key_instances": DodoPaymentsEndpointConfig(path="/license_key_instances", primary_keys=["id"]),
    "entitlements": DodoPaymentsEndpointConfig(path="/entitlements", primary_keys=["id"]),
    "credit_entitlements": DodoPaymentsEndpointConfig(path="/credit-entitlements", primary_keys=["id"]),
    # Line items take no date filter of their own, so incremental runs filter the parent payment
    # listing on `created_at_gte` instead. `refundable_amount` drops when a payment is refunded,
    # hence the re-read window.
    "payment_line_items": DodoPaymentsEndpointConfig(
        path="/payments/{payment_id}/line-items",
        primary_keys=["payment_id", "items_id"],
        incremental_fields=[incremental_field("payment_created_at")],
        partition_key="payment_created_at",
        paginated=False,
        restated=True,
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="payments",
            resolve_param="payment_id",
            resolve_field="payment_id",
            # The line-items body carries `currency` beside `items`, not on each item, so it comes
            # from the parent payment instead.
            include_from_parent=["payment_id", "created_at", "currency"],
            parent_field_renames={
                "payment_id": "payment_id",
                "created_at": "payment_created_at",
                "currency": "currency",
            },
        ),
    ),
    # One row per billing period. The current period's usage grows until it closes, so this is
    # full refresh only.
    "subscription_usage_history": DodoPaymentsEndpointConfig(
        path="/subscriptions/{subscription_id}/usage-history",
        primary_keys=["subscription_id", "start_date"],
        partition_key="start_date",
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="subscriptions",
            resolve_param="subscription_id",
            resolve_field="subscription_id",
            include_from_parent=["subscription_id"],
            parent_field_renames={"subscription_id": "subscription_id"},
        ),
    ),
    "payout_breakup_details": DodoPaymentsEndpointConfig(
        path="/payouts/{payout_id}/breakup/details",
        primary_keys=["payout_id", "id"],
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="payouts",
            resolve_param="payout_id",
            resolve_field="payout_id",
            include_from_parent=["payout_id"],
            parent_field_renames={"payout_id": "payout_id"},
        ),
    ),
    # Balance rows already carry `credit_entitlement_id`, so nothing is copied from the parent.
    "credit_entitlement_balances": DodoPaymentsEndpointConfig(
        path="/credit-entitlements/{credit_entitlement_id}/balances",
        primary_keys=["credit_entitlement_id", "id"],
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="credit_entitlements",
            resolve_param="credit_entitlement_id",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    # Ledger entries are immutable and take their own `start_date` filter, so incremental runs
    # filter each ledger request and walk the parents in full. The parents are themselves a
    # fan-out (entitlement -> customer balance), so this chain carries no resume state.
    "credit_entitlement_ledger": DodoPaymentsEndpointConfig(
        path="/credit-entitlements/{credit_entitlement_id}/balances/{customer_id}/ledger",
        primary_keys=["credit_entitlement_id", "customer_id", "id"],
        start_param="start_date",
        incremental_fields=[incremental_field("created_at")],
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="credit_entitlement_balances",
            resolve_param="customer_id",
            resolve_field="customer_id",
            include_from_parent=[],
        ),
        extra_resolve_fields={"credit_entitlement_id": "credit_entitlement_id"},
    ),
    # `remaining_amount` and `is_expired` change after a grant is created and there is no date
    # filter, so this is full refresh only.
    "credit_entitlement_grants": DodoPaymentsEndpointConfig(
        path="/credit-entitlements/{credit_entitlement_id}/balances/{customer_id}/grants",
        primary_keys=["credit_entitlement_id", "customer_id", "id"],
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="credit_entitlement_balances",
            resolve_param="customer_id",
            resolve_field="customer_id",
            include_from_parent=[],
        ),
        extra_resolve_fields={"credit_entitlement_id": "credit_entitlement_id"},
    ),
    # One row per currency. The body is `{"items": [...], "total_balance_usd": ...}` with no
    # pagination, and each wallet already carries `customer_id`.
    "customer_wallets": DodoPaymentsEndpointConfig(
        path="/customers/{customer_id}/wallets",
        primary_keys=["customer_id", "currency"],
        paginated=False,
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="customers",
            resolve_param="customer_id",
            resolve_field="customer_id",
            include_from_parent=[],
        ),
    ),
    # Wallet transactions are immutable, but a customer gets them long after the customer is
    # created and the ledger takes no date filter, so this is full refresh only. Each row already
    # carries `customer_id`.
    "customer_wallet_ledger_entries": DodoPaymentsEndpointConfig(
        path="/customers/{customer_id}/wallets/ledger-entries",
        primary_keys=["customer_id", "id"],
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="customers",
            resolve_param="customer_id",
            resolve_field="customer_id",
            include_from_parent=[],
        ),
    ),
    # A grant's `status` moves through delivery and revocation, and there is no date filter, so
    # this is full refresh only. Each row already carries `entitlement_id`.
    "entitlement_grants": DodoPaymentsEndpointConfig(
        path="/entitlements/{id}/grants",
        primary_keys=["entitlement_id", "id"],
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="entitlements",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    # A customer gets emails long after the customer is created, so the customer listing cannot
    # window them, and an email's delivery `status` changes after it is sent. Full refresh only.
    "customer_emails": DodoPaymentsEndpointConfig(
        path="/customers/{customer_id}/emails",
        primary_keys=["customer_id", "email_log_id"],
        fanout=DependentEndpointConfig(
            child_response_actions=SKIP_MISSING_PARENT,
            parent_name="customers",
            resolve_param="customer_id",
            resolve_field="customer_id",
            include_from_parent=["customer_id"],
            parent_field_renames={"customer_id": "customer_id"},
        ),
    ),
}

ENDPOINTS = tuple(DODOPAYMENTS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DODOPAYMENTS_ENDPOINTS.items() if config.incremental_fields
}

INCREMENTAL_ENDPOINTS = tuple(INCREMENTAL_FIELDS.keys())
