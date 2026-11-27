from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.paddle.constants import (
    ADJUSTMENT_RESOURCE_NAME,
    CUSTOMER_ADDRESS_RESOURCE_NAME,
    CUSTOMER_BUSINESS_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_GROUP_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    EXPLORE_METRICS_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_HISTORY_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
)
from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

PAGE_SIZE = 200

ENDPOINTS = [
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
    ADJUSTMENT_RESOURCE_NAME,
    EXPLORE_METRICS_RESOURCE_NAME,
    DISCOUNT_GROUP_RESOURCE_NAME,
    CUSTOMER_ADDRESS_RESOURCE_NAME,
    CUSTOMER_BUSINESS_RESOURCE_NAME,
    SUBSCRIPTION_HISTORY_RESOURCE_NAME,
]

# Explore metrics need the separate `metrics.read` permission, so the connection check skips them
# and a key without it can still sync the other tables. The connection check also skips the newer
# tables, so a key made for the original tables still connects.
CREDENTIAL_CHECK_ENDPOINTS = [
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
    ADJUSTMENT_RESOURCE_NAME,
]

# Tables with a fixed Paddle schema in external_table_definitions.
MANAGED_SCHEMA_ENDPOINTS = frozenset(CREDENTIAL_CHECK_ENDPOINTS)

# Top-level list endpoints whose path differs from the table name.
ENDPOINT_PATHS = {DISCOUNT_GROUP_RESOURCE_NAME: "discount-groups"}

# Partition keys for top-level tables without an incremental field.
PARTITION_KEYS = {DISCOUNT_GROUP_RESOURCE_NAME: "created_at"}

# Addresses and businesses list only `active` rows by default. Archived ones are still referenced by
# older subscriptions and transactions.
ALL_STATUSES = "active,archived"


@dataclass(frozen=True)
class PaddleFanoutEndpoint:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


FANOUT_ENDPOINTS: dict[str, PaddleFanoutEndpoint] = {
    CUSTOMER_RESOURCE_NAME: PaddleFanoutEndpoint(name=CUSTOMER_RESOURCE_NAME, path="customers"),
    SUBSCRIPTION_RESOURCE_NAME: PaddleFanoutEndpoint(name=SUBSCRIPTION_RESOURCE_NAME, path="subscriptions"),
    CUSTOMER_ADDRESS_RESOURCE_NAME: PaddleFanoutEndpoint(
        name=CUSTOMER_ADDRESS_RESOURCE_NAME,
        path="customers/{customer_id}/addresses",
        primary_keys=["customer_id", "id"],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name=CUSTOMER_RESOURCE_NAME,
            resolve_param="customer_id",
            resolve_field="id",
            include_from_parent=[],
            parent_params={"order_by": "id[ASC]", "status": ALL_STATUSES},
            child_params={"order_by": "id[ASC]", "status": ALL_STATUSES},
        ),
    ),
    CUSTOMER_BUSINESS_RESOURCE_NAME: PaddleFanoutEndpoint(
        name=CUSTOMER_BUSINESS_RESOURCE_NAME,
        path="customers/{customer_id}/businesses",
        primary_keys=["customer_id", "id"],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name=CUSTOMER_RESOURCE_NAME,
            resolve_param="customer_id",
            resolve_field="id",
            include_from_parent=[],
            parent_params={"order_by": "id[ASC]", "status": ALL_STATUSES},
            child_params={"order_by": "id[ASC]", "status": ALL_STATUSES},
        ),
    ),
    SUBSCRIPTION_HISTORY_RESOURCE_NAME: PaddleFanoutEndpoint(
        name=SUBSCRIPTION_HISTORY_RESOURCE_NAME,
        path="subscriptions/{subscription_id}/history",
        primary_keys=["subscription_id", "id"],
        partition_key="occurred_at",
        fanout=DependentEndpointConfig(
            parent_name=SUBSCRIPTION_RESOURCE_NAME,
            resolve_param="subscription_id",
            resolve_field="id",
            include_from_parent=[],
            parent_params={"order_by": "id[ASC]"},
            child_params={"order_by": "id[ASC]"},
        ),
    ),
}

# Paddle refreshes Explore data on a 24-hour cycle, so recent buckets can change after a sync.
EXPLORE_METRICS_LOOKBACK_SECONDS = 60 * 60 * 24 * 3

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TRANSACTION_RESOURCE_NAME: [
        {
            "label": "billed_at",
            "type": IncrementalFieldType.DateTime,
            "field": "billed_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    SUBSCRIPTION_HISTORY_RESOURCE_NAME: [
        {
            "label": "occurred_at",
            "type": IncrementalFieldType.DateTime,
            "field": "occurred_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    EXPLORE_METRICS_RESOURCE_NAME: [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
