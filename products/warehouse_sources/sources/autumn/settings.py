from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

AUTUMN_BASE_URL = "https://api.useautumn.com"

AUTUMN_API_VERSION_2_3_0 = "2.3.0"
AUTUMN_API_VERSION_2_4_0 = "2.4.0"

# From 2.4.0 Autumn rejects list requests whose limit exceeds 200.
AUTUMN_V2_4_MAX_PAGE_SIZE = 200

# Autumn timestamps are epoch milliseconds, so "datetime" partition mode (which expects epoch
# seconds for integer values) can't be used. Numerical bucketing on the raw value with a
# one-week bucket size yields the same stable weekly partitions.
PARTITION_BUCKET_MILLISECONDS = 7 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class AutumnEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    data_selector: str = "list"
    # Cursor-paginated endpoints take start_cursor/limit in the POST body and return
    # next_cursor (null when exhausted); the rest return everything in one page.
    paginated: bool = True
    page_size: int = 500
    partition_key: str | None = None
    # Field the server-side custom_range filter applies to (epoch milliseconds). Only
    # events.list supports a time-range filter; every other list endpoint is full refresh.
    incremental_range_field: str | None = None
    # Customer-scoped endpoints take a single customer_id, so the table walks customers.list and
    # issues one request per customer, stamping customer_id onto each row.
    customer_fan_out: bool = False
    # Balance-scoped endpoints take a customer_id and a feature_id, so the table walks customers.list
    # and issues paginated requests for each feature key in the customer's balances.
    customer_feature_fan_out: bool = False
    # Static body params sent on every request, e.g. statuses to include expired history.
    extra_body: dict[str, Any] = field(default_factory=dict)
    unsupported_api_versions: tuple[str, ...] = ()


AUTUMN_ENDPOINTS: dict[str, AutumnEndpointConfig] = {
    "Customers": AutumnEndpointConfig(
        name="Customers",
        path="/v1/customers.list",
        primary_keys=["id"],
        # Customer objects are wide (subscriptions, purchases, billing controls), so keep
        # pages small; customers.list is also rate-limited to 5 req/s per org.
        page_size=100,
        partition_key="created_at",
    ),
    "Events": AutumnEndpointConfig(
        name="Events",
        path="/v1/events.list",
        primary_keys=["id"],
        page_size=1000,
        partition_key="timestamp",
        incremental_range_field="timestamp",
    ),
    "Features": AutumnEndpointConfig(
        name="Features",
        path="/v1/features.list",
        primary_keys=["id"],
        paginated=False,
    ),
    "Plans": AutumnEndpointConfig(
        name="Plans",
        path="/v1/plans.list",
        primary_keys=["id"],
        paginated=False,
    ),
    "Entities": AutumnEndpointConfig(
        name="Entities",
        path="/v1/entities.list",
        # Entity ids are only unique within their parent customer.
        primary_keys=["customer_id", "id"],
        page_size=100,
        partition_key="created_at",
    ),
    "Invoices": AutumnEndpointConfig(
        name="Invoices",
        path="/v1/invoices.list",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    # rewards.list returns two root arrays; each becomes its own table via data_selector.
    "Coupons": AutumnEndpointConfig(
        name="Coupons",
        path="/v1/rewards.list",
        primary_keys=["id"],
        data_selector="coupons",
        paginated=False,
    ),
    "FeatureGrants": AutumnEndpointConfig(
        name="FeatureGrants",
        path="/v1/rewards.list",
        primary_keys=["id"],
        data_selector="feature_grants",
        paginated=False,
    ),
    "Licenses": AutumnEndpointConfig(
        name="Licenses",
        path="/v1/licenses.list",
        # A pool has no id of its own; a license plan can be offered by several parent plans.
        primary_keys=["customer_id", "parent_plan_id", "license_plan_id"],
        paginated=False,
        customer_fan_out=True,
    ),
    # The cross-customer lists default to live rows only, so ask for expired history too.
    "Balances": AutumnEndpointConfig(
        name="Balances",
        path="/v1/balances.list",
        # id can be a caller-chosen balance_id; internal_id is the balance row itself.
        primary_keys=["customer_id", "internal_id"],
        page_size=AUTUMN_V2_4_MAX_PAGE_SIZE,
        partition_key="created_at",
        extra_body={"statuses": ["active", "expired"]},
    ),
    "Subscriptions": AutumnEndpointConfig(
        name="Subscriptions",
        path="/v1/subscriptions.list",
        # id falls back to a caller-chosen subscription_id, so it is only unique per customer.
        primary_keys=["customer_id", "id"],
        page_size=AUTUMN_V2_4_MAX_PAGE_SIZE,
        partition_key="created_at",
        extra_body={"statuses": ["active", "scheduled", "expired"]},
    ),
    "Purchases": AutumnEndpointConfig(
        name="Purchases",
        path="/v1/purchases.list",
        primary_keys=["customer_id", "id"],
        page_size=AUTUMN_V2_4_MAX_PAGE_SIZE,
        partition_key="created_at",
        extra_body={"statuses": ["active", "scheduled", "expired"]},
    ),
    "BalanceLedger": AutumnEndpointConfig(
        name="BalanceLedger",
        path="/v1/balances.list_ledger",
        # One entry can show in the ledger of each balance that paid for it, so the key carries
        # the feature whose balance was listed.
        primary_keys=["customer_id", "balance_feature_id", "id"],
        page_size=AUTUMN_V2_4_MAX_PAGE_SIZE,
        partition_key="occurred_at",
        customer_feature_fan_out=True,
        unsupported_api_versions=(AUTUMN_API_VERSION_2_3_0,),
    ),
}

ENDPOINTS = tuple(AUTUMN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Events": [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.Integer,
            "field": "timestamp",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
