from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

GUMROAD_BASE_URL = "https://api.gumroad.com"

# Gumroad's list endpoints take no page-size parameter — the server fixes it per resource
# (10 for sales/products/payouts, 100 for subscribers and reviews). `page_size` below is only
# carried to satisfy the fan-out helper's protocol; no request ever sends it.
SERVER_FIXED_PAGE_SIZE = 10

# Response wrapper key holding the next cursor, and the request param that consumes it.
PAGE_KEY_CURSOR_PATH = "next_page_key"
PAGE_KEY_PARAM = "page_key"

# `after` filters on `created_at >= <date>` at day granularity, so a resumed sync always
# re-reads from midnight of the watermark's day. The merge dedupes those rows on the primary key.
INCREMENTAL_START_PARAM = "after"


@dataclass
class GumroadEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_key: list[str]
    # Endpoints whose response carries `next_page_key`; the rest return the full collection.
    paginated: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = SERVER_FIXED_PAGE_SIZE
    extra_params: dict[str, str] = field(default_factory=dict)
    fanout: DependentEndpointConfig | None = None
    # Path probed to tell whether the token carries the OAuth scope this table needs.
    permission_probe_path: str = "/v2/user"
    required_scope: str = "view_public"


# Every product-scoped table fans out over `/v2/products`, carrying the parent's `id` in as
# `product_id`. Universal offer codes and global custom fields are returned under every product
# they apply to, so the parent id is part of those tables' primary keys.
_PRODUCT_FANOUT = DependentEndpointConfig(
    parent_name="products",
    resolve_param="product_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "product_id"},
)


GUMROAD_ENDPOINTS: dict[str, GumroadEndpointConfig] = {
    "sales": GumroadEndpointConfig(
        name="sales",
        path="/v2/sales",
        data_selector="sales",
        primary_key=["id"],
        incremental_fields=[incremental_field("created_at")],
        default_incremental_field="created_at",
        partition_key="created_at",
        permission_probe_path="/v2/sales",
        required_scope="view_sales",
    ),
    "products": GumroadEndpointConfig(
        name="products",
        path="/v2/products",
        data_selector="products",
        primary_key=["id"],
        # The product payload carries no timestamp at all (no created_at/updated_at), so there
        # is nothing to filter or partition on — full refresh.
        permission_probe_path="/v2/products",
    ),
    "payouts": GumroadEndpointConfig(
        name="payouts",
        path="/v2/payouts",
        data_selector="payouts",
        primary_key=["id"],
        incremental_fields=[incremental_field("created_at")],
        default_incremental_field="created_at",
        partition_key="created_at",
        # Upcoming (not yet paid out) payouts are prepended with a null id, which would break the
        # primary key. Ask for settled payouts only.
        extra_params={"include_upcoming": "false"},
        permission_probe_path="/v2/payouts",
        required_scope="view_payouts",
    ),
    "subscribers": GumroadEndpointConfig(
        name="subscribers",
        path="/v2/products/{product_id}/subscribers",
        data_selector="subscribers",
        # Subscription ids are account-wide unique (the top-level `/v2/subscribers/{id}` endpoint
        # resolves them without a product), and each row already carries its own `product_id`.
        primary_key=["id"],
        partition_key="created_at",
        # Pagination is opt-in on this endpoint; without it the whole collection comes back in
        # one response and `next_page_key` is never set.
        extra_params={"paginated": "true"},
        fanout=DependentEndpointConfig(
            parent_name="products",
            resolve_param="product_id",
            resolve_field="id",
            # The subscriber payload already carries `product_id`; nothing to copy down.
            include_from_parent=[],
        ),
        permission_probe_path="/v2/sales",
        required_scope="view_sales",
    ),
    "product_reviews": GumroadEndpointConfig(
        name="product_reviews",
        path="/v2/products/{product_id}/reviews",
        data_selector="product_reviews",
        primary_key=["product_id", "id"],
        partition_key="created_at",
        fanout=_PRODUCT_FANOUT,
        permission_probe_path="/v2/products",
    ),
    "offer_codes": GumroadEndpointConfig(
        name="offer_codes",
        path="/v2/products/{product_id}/offer_codes",
        data_selector="offer_codes",
        # Universal offer codes are listed under every product, so the same code id repeats.
        primary_key=["product_id", "id"],
        paginated=False,
        fanout=_PRODUCT_FANOUT,
        permission_probe_path="/v2/products",
    ),
    "variant_categories": GumroadEndpointConfig(
        name="variant_categories",
        path="/v2/products/{product_id}/variant_categories",
        data_selector="variant_categories",
        primary_key=["product_id", "id"],
        paginated=False,
        fanout=_PRODUCT_FANOUT,
        permission_probe_path="/v2/products",
    ),
    "custom_fields": GumroadEndpointConfig(
        name="custom_fields",
        path="/v2/products/{product_id}/custom_fields",
        data_selector="custom_fields",
        # Global custom fields are attached to many products and repeat across them.
        primary_key=["product_id", "id"],
        paginated=False,
        fanout=_PRODUCT_FANOUT,
        permission_probe_path="/v2/products",
    ),
}

ENDPOINTS = tuple(GUMROAD_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GUMROAD_ENDPOINTS.items()
}
