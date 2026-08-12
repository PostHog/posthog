from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# ShipStation runs two live vendor APIs. v1 is the original ssapi.shipstation.com API (HTTP Basic
# with an API key + secret, US Pacific DateTimes). v2 is the ShipStation API v2 (ShipEngine-based)
# at api.shipstation.com/v2 — a single API-Key header, ISO 8601 UTC timestamps, and an entirely
# different resource model (shipments/labels/carriers/…), not a reskin of v1. The vendor has
# deprecated v1; new sources start on v2.
SHIPSTATION_V1 = "v1"
SHIPSTATION_V2 = "v2"
SHIPSTATION_SUPPORTED_VERSIONS = (SHIPSTATION_V1, SHIPSTATION_V2)
SHIPSTATION_DEFAULT_VERSION = SHIPSTATION_V2


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


def _v2_datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# ShipStation API v2 (ShipEngine) — https://docs.shipstation.com / OpenAPI at
# https://shipengine.github.io/shipengine-openapi/. Base https://api.shipstation.com/v2. List
# responses wrap rows under the plural resource key and (for the paginated ones) carry
# `page`/`pages`/`total`/`links`; timestamps are ISO 8601 UTC and the date filters are
# `created_at_start` / `modified_at_start`. Carriers, warehouses and tags are small reference
# lists with no pagination envelope or date filter, so they full-refresh.
SHIPSTATION_V2_ENDPOINTS: dict[str, ShipStationEndpointConfig] = {
    "shipments": ShipStationEndpointConfig(
        name="shipments",
        path="/shipments",
        primary_key="shipment_id",
        data_key="shipments",
        partition_key="created_at",
        incremental_params={
            "modified_at": "modified_at_start",
            "created_at": "created_at_start",
        },
        sort_by={
            "modified_at": "modified_at",
            "created_at": "created_at",
        },
        incremental_fields=[
            _v2_datetime_incremental_field("modified_at"),
            _v2_datetime_incremental_field("created_at"),
        ],
    ),
    "labels": ShipStationEndpointConfig(
        name="labels",
        path="/labels",
        primary_key="label_id",
        data_key="labels",
        partition_key="created_at",
        incremental_params={"created_at": "created_at_start"},
        sort_by={"created_at": "created_at"},
        incremental_fields=[
            _v2_datetime_incremental_field("created_at"),
        ],
    ),
    "batches": ShipStationEndpointConfig(
        name="batches",
        path="/batches",
        primary_key="batch_id",
        data_key="batches",
        partition_key="created_at",
        incremental_params={"created_at": "created_at_start"},
        sort_by={"created_at": "created_at"},
        incremental_fields=[
            _v2_datetime_incremental_field("created_at"),
        ],
    ),
    "manifests": ShipStationEndpointConfig(
        name="manifests",
        path="/manifests",
        primary_key="manifest_id",
        data_key="manifests",
        partition_key="created_at",
        # `/manifests` filters on `created_at_start` but documents no sortBy enum — the window
        # plus merge-on-pk keeps incremental correct (same shape as v1 fulfillments).
        incremental_params={"created_at": "created_at_start"},
        incremental_fields=[
            _v2_datetime_incremental_field("created_at"),
        ],
    ),
    "pickups": ShipStationEndpointConfig(
        name="pickups",
        path="/pickups",
        primary_key="pickup_id",
        data_key="pickups",
        partition_key="created_at",
        incremental_params={"created_at": "created_at_start"},
        incremental_fields=[
            _v2_datetime_incremental_field("created_at"),
        ],
    ),
    "carriers": ShipStationEndpointConfig(
        name="carriers",
        path="/carriers",
        primary_key="carrier_id",
        data_key="carriers",
        paginated=False,
    ),
    "warehouses": ShipStationEndpointConfig(
        name="warehouses",
        path="/warehouses",
        primary_key="warehouse_id",
        data_key="warehouses",
        paginated=False,
    ),
    "tags": ShipStationEndpointConfig(
        name="tags",
        path="/tags",
        primary_key="tag_id",
        data_key="tags",
        paginated=False,
    ),
}

V2_ENDPOINTS = tuple(SHIPSTATION_V2_ENDPOINTS.keys())

V2_INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHIPSTATION_V2_ENDPOINTS.items() if config.incremental_fields
}


def endpoints_for_version(api_version: str) -> dict[str, ShipStationEndpointConfig]:
    """The endpoint catalog for a resolved version pin. v1 and v2 expose different resources."""
    return SHIPSTATION_V2_ENDPOINTS if api_version == SHIPSTATION_V2 else SHIPSTATION_ENDPOINTS


def schema_catalog_for_version(api_version: str) -> tuple[tuple[str, ...], dict[str, list[IncrementalField]]]:
    """The `(endpoint names, incremental fields)` pair `get_schemas` builds from, per version."""
    if api_version == SHIPSTATION_V2:
        return V2_ENDPOINTS, V2_INCREMENTAL_FIELDS
    return ENDPOINTS, INCREMENTAL_FIELDS
