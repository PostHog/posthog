from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# X-Series v2.0 list pages cap at 200 items.
PAGE_SIZE = 200

# Every X-Series v2.0 record carries a monotonically increasing integer
# `version`; the same `after=<version>` param used for keyset pagination doubles
# as a lossless incremental cursor, so the menu is shared across endpoints.
_VERSION_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "version",
        "type": IncrementalFieldType.Integer,
        "field": "version",
        "field_type": IncrementalFieldType.Integer,
    },
]


# - "version": keyset over the record `version` (`after=<version>`), the X-Series default.
# - "after_cursor": `after=<page_info.last_seen>`, for endpoints whose records carry no version.
# - "before_id": `before=<id of the last item>`, newest to oldest.
# - "single_page": the endpoint takes no page cursor and returns the full list.
Pagination = Literal["version", "after_cursor", "before_id", "single_page"]


@dataclass(frozen=True)
class LightspeedRetailEndpointConfig:
    name: str
    path: str
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_VERSION_INCREMENTAL_FIELDS))
    # Stable creation-time field used for datetime partitioning. Never a
    # version/updated-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None
    pagination: Pagination = "version"
    data_selector: str = "data"
    sort_mode: Literal["asc", "desc"] = "asc"
    # Emits one row per entry of this nested list, tagged with the parent record's id under
    # `nested_parent_key`, instead of one row per record.
    nested_rows_field: Optional[str] = None
    nested_parent_key: Optional[str] = None


LIGHTSPEED_RETAIL_ENDPOINTS: dict[str, LightspeedRetailEndpointConfig] = {
    "sales": LightspeedRetailEndpointConfig(
        name="sales",
        path="/sales",
        partition_key="sale_date",
    ),
    "customers": LightspeedRetailEndpointConfig(
        name="customers",
        path="/customers",
        partition_key="created_at",
    ),
    "products": LightspeedRetailEndpointConfig(
        name="products",
        path="/products",
        partition_key="created_at",
    ),
    "inventory": LightspeedRetailEndpointConfig(
        name="inventory",
        path="/inventory",
    ),
    "outlets": LightspeedRetailEndpointConfig(
        name="outlets",
        path="/outlets",
    ),
    "registers": LightspeedRetailEndpointConfig(
        name="registers",
        path="/registers",
    ),
    "users": LightspeedRetailEndpointConfig(
        name="users",
        path="/users",
    ),
    "taxes": LightspeedRetailEndpointConfig(
        name="taxes",
        path="/taxes",
    ),
    "consignments": LightspeedRetailEndpointConfig(
        name="consignments",
        path="/consignments",
        partition_key="created_at",
    ),
    "consignment_products": LightspeedRetailEndpointConfig(
        name="consignment_products",
        path="/consignments/{consignment_id}/products",
        # Line items carry no id of their own; a product appears once per consignment.
        primary_key=["consignment_id", "product_id"],
        # Child versions only ascend within one consignment, so a fan-out run is not in
        # global version order and can't drive a watermark.
        incremental_fields=[],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="consignments",
            resolve_param="consignment_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "consignment_id"},
        ),
    ),
    "suppliers": LightspeedRetailEndpointConfig(
        name="suppliers",
        path="/suppliers",
    ),
    "payment_types": LightspeedRetailEndpointConfig(
        name="payment_types",
        path="/payment_types",
    ),
    "product_categories": LightspeedRetailEndpointConfig(
        name="product_categories",
        path="/product_categories",
        incremental_fields=[],
        pagination="after_cursor",
        data_selector="data.categories",
    ),
    "stock_adjustments": LightspeedRetailEndpointConfig(
        name="stock_adjustments",
        path="/stock_adjustments",
        partition_key="created_at",
    ),
    "promotions": LightspeedRetailEndpointConfig(
        name="promotions",
        path="/promotions",
        incremental_fields=[],
        # `page_size` is the only paging param and caps the list, so it is not sent.
        pagination="single_page",
    ),
    "promo_codes": LightspeedRetailEndpointConfig(
        name="promo_codes",
        path="/promotions/{promotion_id}/promocodes",
        primary_key=["promotion_id", "id"],
        incremental_fields=[],
        partition_key="created_at",
        pagination="single_page",
        fanout=DependentEndpointConfig(
            parent_name="promotions",
            resolve_param="promotion_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "promotion_id"},
        ),
    ),
    "gift_cards": LightspeedRetailEndpointConfig(
        name="gift_cards",
        path="/gift_cards",
        incremental_fields=[],
        partition_key="created_at",
        pagination="before_id",
        sort_mode="desc",
    ),
    "gift_card_transactions": LightspeedRetailEndpointConfig(
        name="gift_card_transactions",
        path="/gift_cards",
        primary_key=["gift_card_id", "id"],
        incremental_fields=[],
        partition_key="created_at",
        pagination="before_id",
        sort_mode="desc",
        nested_rows_field="gift_card_transactions",
        nested_parent_key="gift_card_id",
    ),
}

ENDPOINTS = tuple(LIGHTSPEED_RETAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LIGHTSPEED_RETAIL_ENDPOINTS.items() if config.incremental_fields
}
