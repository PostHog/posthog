from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ShipStationEndpointConfig:
    name: str
    path: str
    primary_key: str
    # Body key the list of rows lives under (orders/shipments/etc. wrap rows and
    # include total/page/pages); None for endpoints returning a bare array.
    data_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental cursor field to the server-side query param that
    # filters on it (e.g. modifyDate -> modifyDateStart).
    incremental_params: dict[str, str] = field(default_factory=dict)
    # Maps a cursor field to the API's sortBy enum value. Only set where the
    # docs list the value for the endpoint; unset means no explicit sort.
    sort_by: dict[str, str] = field(default_factory=dict)
    # Stable creation-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    paginated: bool = True


# ShipStation v1 (ssapi.shipstation.com) — all DateTime values are US Pacific
# time, not UTC; the transport converts cursor values before filtering.
SHIPSTATION_ENDPOINTS: dict[str, ShipStationEndpointConfig] = {
    "orders": ShipStationEndpointConfig(
        name="orders",
        path="/orders",
        primary_key="orderId",
        data_key="orders",
        partition_key="createDate",
        incremental_params={
            "modifyDate": "modifyDateStart",
            "createDate": "createDateStart",
        },
        sort_by={
            "modifyDate": "ModifyDate",
            "createDate": "CreateDate",
        },
        incremental_fields=[
            {
                "label": "modifyDate",
                "type": IncrementalFieldType.DateTime,
                "field": "modifyDate",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "createDate",
                "type": IncrementalFieldType.DateTime,
                "field": "createDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "shipments": ShipStationEndpointConfig(
        name="shipments",
        path="/shipments",
        primary_key="shipmentId",
        data_key="shipments",
        partition_key="createDate",
        incremental_params={"createDate": "createDateStart"},
        sort_by={"createDate": "CreateDate"},
        incremental_fields=[
            {
                "label": "createDate",
                "type": IncrementalFieldType.DateTime,
                "field": "createDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "fulfillments": ShipStationEndpointConfig(
        name="fulfillments",
        path="/fulfillments",
        primary_key="fulfillmentId",
        data_key="fulfillments",
        partition_key="createDate",
        incremental_params={"createDate": "createDateStart"},
        # The fulfillments docs don't list a sortBy enum, so no explicit sort —
        # the createDateStart window plus merge-on-pk keeps incremental correct.
        incremental_fields=[
            {
                "label": "createDate",
                "type": IncrementalFieldType.DateTime,
                "field": "createDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "products": ShipStationEndpointConfig(
        name="products",
        path="/products",
        primary_key="productId",
        data_key="products",
    ),
    "customers": ShipStationEndpointConfig(
        name="customers",
        path="/customers",
        primary_key="customerId",
        data_key="customers",
    ),
    "stores": ShipStationEndpointConfig(
        name="stores",
        path="/stores",
        primary_key="storeId",
        paginated=False,
    ),
    "warehouses": ShipStationEndpointConfig(
        name="warehouses",
        path="/warehouses",
        primary_key="warehouseId",
        paginated=False,
    ),
}

ENDPOINTS = tuple(SHIPSTATION_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHIPSTATION_ENDPOINTS.items() if config.incremental_fields
}
