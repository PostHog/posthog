from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.kajabi.com/v1"
PAGE_SIZE = 100


@frozen
class KajabiEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"
    sort_field: str | None = "created_at"
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


ENDPOINTS = {
    "contacts": KajabiEndpoint(name="contacts", path="contacts"),
    "customers": KajabiEndpoint(name="customers", path="customers"),
    "purchases": KajabiEndpoint(name="purchases", path="purchases"),
    "offers": KajabiEndpoint(name="offers", path="offers", partition_key=None, sort_field="title"),
    "products": KajabiEndpoint(name="products", path="products", sort_field="title"),
    "courses": KajabiEndpoint(name="courses", path="courses", sort_field="title"),
    "orders": KajabiEndpoint(name="orders", path="orders"),
    "order_items": KajabiEndpoint(name="order_items", path="order_items"),
    "transactions": KajabiEndpoint(name="transactions", path="transactions", sort_field=None),
    "contact_tags": KajabiEndpoint(name="contact_tags", path="contact_tags", partition_key=None, sort_field="name"),
    "contact_offers": KajabiEndpoint(
        name="contact_offers",
        path="contacts/{contact_id}/relationships/offers",
        primary_keys=("contact_id", "id"),
        partition_key=None,
        fanout=DependentEndpointConfig(
            parent_name="contacts",
            resolve_param="contact_id",
            resolve_field="path_id",
            include_from_parent=["id"],
            parent_field_renames={"id": "contact_id"},
        ),
    ),
    "contact_taggings": KajabiEndpoint(
        name="contact_taggings",
        path="contacts/{contact_id}/relationships/tags",
        primary_keys=("contact_id", "id"),
        partition_key=None,
        fanout=DependentEndpointConfig(
            parent_name="contacts",
            resolve_param="contact_id",
            resolve_field="path_id",
            include_from_parent=["id"],
            parent_field_renames={"id": "contact_id"},
        ),
    ),
}

# Timestamp filters lack account verification. Full refresh also captures changes to existing records.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
