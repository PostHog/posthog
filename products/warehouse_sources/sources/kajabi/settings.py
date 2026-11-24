from dataclasses import field

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen

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
    page_size_param: str | None = "page[size]"
    total_pages_path: str = "meta.total_pages"
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
    "forms": KajabiEndpoint(name="forms", path="forms", partition_key=None, sort_field="title"),
    # Submissions carry no timestamp attribute, but the API still sorts by creation time.
    "form_submissions": KajabiEndpoint(name="form_submissions", path="form_submissions", partition_key=None),
    # Payouts take no page size or sort parameter and report the page count under meta.pagination.
    "payouts": KajabiEndpoint(
        name="payouts",
        path="kajabi_payments_payouts",
        partition_key="initiated_date",
        sort_field=None,
        page_size_param=None,
        total_pages_path="meta.pagination.last",
    ),
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
    "offer_products": KajabiEndpoint(
        name="offer_products",
        path="offers/{offer_id}/relationships/products",
        primary_keys=("offer_id", "id"),
        partition_key=None,
        fanout=DependentEndpointConfig(
            parent_name="offers",
            resolve_param="offer_id",
            resolve_field="path_id",
            include_from_parent=["id"],
            parent_field_renames={"id": "offer_id"},
            # An offer archived between the listing and this fetch answers 404.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

# Timestamp filters lack account verification. Full refresh also captures changes to existing records.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
