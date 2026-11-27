from dataclasses import field
from typing import Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

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
    fanout: DependentEndpointConfig | None = None
    default_incremental_field: str | None = None
    # The shared builder requires this field, but Back Market takes no page-size parameter.
    page_size: int = 0


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
    "backbox_competitors": BackMarketEndpointConfig(
        name="backbox_competitors",
        path="/backbox/v1/competitors/{listingId}",
        primary_keys=["_listings_id", "listing_id", "market"],
        fanout=DependentEndpointConfig(
            parent_name="listings",
            resolve_param="listingId",
            resolve_field="id",
            include_from_parent=["id"],
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "care_folders": BackMarketEndpointConfig(
        name="care_folders",
        path="/sav",
        primary_keys=["id"],
        incremental_fields=[
            {
                "label": "date_modification",
                "type": IncrementalFieldType.DateTime,
                "field": "date_modification",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="date_creation",
    ),
    "returns": BackMarketEndpointConfig(
        name="returns",
        path="/shipping/v1/returns",
        primary_keys=["shipmentId"],
        incremental_fields=[
            {
                "label": "dateCreation",
                "type": IncrementalFieldType.DateTime,
                "field": "dateCreation",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="dateCreation",
    ),
    "buyback_orders": BackMarketEndpointConfig(
        name="buyback_orders",
        path="/buyback/v1/orders",
        primary_keys=["orderPublicId"],
        incremental_fields=[
            {
                "label": "modificationDate",
                "type": IncrementalFieldType.DateTime,
                "field": "modificationDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="creationDate",
    ),
}

ENDPOINTS = tuple(BACK_MARKET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BACK_MARKET_ENDPOINTS.items()
}
