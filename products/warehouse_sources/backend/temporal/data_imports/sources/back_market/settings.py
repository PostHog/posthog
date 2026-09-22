from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Back Market's list endpoints wrap rows in a `results` array alongside a `next` indicator.
DATA_SELECTOR = "results"


@frozen
class BackMarketEndpointConfig:
    name: str
    path: str  # Path under https://www.backmarket.com/ws
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by. None when there's no reliable created_at.
    partition_key: Optional[str] = None


BACK_MARKET_ENDPOINTS: dict[str, BackMarketEndpointConfig] = {
    "orders": BackMarketEndpointConfig(
        name="orders",
        path="/orders",
        primary_keys=["order_id"],
        # The API accepts either filter as an updated-since/created-since timestamp; let the
        # user pick which one drives incremental sync.
        incremental_fields=[
            {
                "label": "date_modification",
                "type": IncrementalFieldType.DateTime,
                "field": "date_modification",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "date_creation",
                "type": IncrementalFieldType.DateTime,
                "field": "date_creation",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="date_creation",
    ),
    "listings": BackMarketEndpointConfig(
        name="listings",
        path="/listings",
        primary_keys=["listing_id"],
        # No documented updated-since filter on listings, so this stays full refresh.
        incremental_fields=[],
        partition_key=None,
    ),
}

ENDPOINTS = tuple(BACK_MARKET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BACK_MARKET_ENDPOINTS.items()
}
