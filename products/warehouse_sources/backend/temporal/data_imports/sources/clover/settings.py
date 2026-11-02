from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

CLOVER_REGION_HOSTS: dict[str, str] = {
    "na": "https://api.clover.com",
    "eu": "https://api.eu.clover.com",
    "latam": "https://api.la.clover.com",
    "sandbox": "https://apisandbox.dev.clover.com",
}
DEFAULT_REGION = "na"
PAGE_SIZE = 1000
FILTER_WINDOW_MS = 89 * 24 * 60 * 60 * 1000


@frozen
class CloverEndpointConfig:
    name: str
    path: str
    permission: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    params: dict[str, Any] = field(default_factory=dict)
    partition_field: str | None = None
    history_field: str | None = None
    fanout: DependentEndpointConfig | None = None
    page_size: int = PAGE_SIZE
    # Enable incremental sync only after a live account confirms that timestamp filters work.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


CLOVER_ENDPOINTS: dict[str, CloverEndpointConfig] = {
    "orders": CloverEndpointConfig(
        name="orders",
        path="orders",
        permission="Read orders",
        partition_field="createdTime",
        history_field="createdTime",
    ),
    "line_items": CloverEndpointConfig(
        name="line_items",
        path="orders/{order_id}/line_items",
        permission="Read orders",
        primary_keys=["order_id", "id"],
        partition_field="order_created_time",
        fanout=DependentEndpointConfig(
            parent_name="orders",
            resolve_param="order_id",
            resolve_field="id",
            include_from_parent=["id", "createdTime"],
            parent_field_renames={"id": "order_id", "createdTime": "order_created_time"},
        ),
    ),
    "payments": CloverEndpointConfig(
        name="payments",
        path="payments",
        permission="Read payments",
        partition_field="createdTime",
        history_field="createdTime",
    ),
    "refunds": CloverEndpointConfig(
        name="refunds",
        path="refunds",
        permission="Read payments",
        partition_field="createdTime",
        history_field="createdTime",
    ),
    "credit_refunds": CloverEndpointConfig(
        name="credit_refunds", path="credit_refunds", permission="Read payments", partition_field="createdTime"
    ),
    "items": CloverEndpointConfig(name="items", path="items", permission="Read inventory"),
    "categories": CloverEndpointConfig(name="categories", path="categories", permission="Read inventory"),
    "modifier_groups": CloverEndpointConfig(
        name="modifier_groups", path="modifier_groups", permission="Read inventory"
    ),
    "modifiers": CloverEndpointConfig(name="modifiers", path="modifiers", permission="Read inventory"),
    "customers": CloverEndpointConfig(
        name="customers", path="customers", permission="Read customers", partition_field="customerSince"
    ),
    "employees": CloverEndpointConfig(name="employees", path="employees", permission="Read employees"),
    "shifts": CloverEndpointConfig(name="shifts", path="shifts", permission="Read employees"),
    "tenders": CloverEndpointConfig(name="tenders", path="tenders", permission="Read merchant"),
    "discounts": CloverEndpointConfig(name="discounts", path="discounts", permission="Read inventory"),
    "tax_rates": CloverEndpointConfig(name="tax_rates", path="tax_rates", permission="Read inventory"),
}

ENDPOINTS = tuple(CLOVER_ENDPOINTS)
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLOVER_ENDPOINTS.items()
}
