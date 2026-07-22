from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

AUTUMN_BASE_URL = "https://api.useautumn.com"

# Autumn timestamps are epoch milliseconds, so "datetime" partition mode (which expects epoch
# seconds for integer values) can't be used. Numerical bucketing on the raw value with a
# one-week bucket size yields the same stable weekly partitions.
PARTITION_BUCKET_MILLISECONDS = 7 * 24 * 60 * 60 * 1000


@dataclass
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
