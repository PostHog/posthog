from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Vendr's documented maximum page size for every list endpoint (default is 10 if unset).
PAGE_SIZE = 100


# frozen=False: VendrEndpointConfig is passed as `endpoint_configs: Mapping[str, FanoutEndpointLike]`,
# and mypy treats a frozen dataclass's fields as read-only, which is incompatible with that
# Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class VendrEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Value for this endpoint's own `sortBy` enum. The accepted values differ per endpoint
    # (Companies/Categories: "name"; the two company-scoped lists: "name" or "sortOrder"), so
    # it's declared per endpoint rather than shared, and always sent explicitly so page
    # boundaries stay stable even if Vendr changes an implicit default.
    sort_by: str
    page_size: int = PAGE_SIZE
    # Required by the shared fan-out helper's `FanoutEndpointLike` protocol. Vendr's catalog API
    # documents no updated-since/created-since filter on any endpoint, so every table here is
    # full refresh.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


# Product families and products both hang off a company and are fetched with the company's `id`
# bound into the `{companyId}` path placeholder. Vendr's single-resource lookups
# (`GET /v1/catalog/product-families/{id}`, `GET /v1/catalog/products/{id}`) take no company
# context at all, which confirms `id` is a global identifier — so the child tables key on `id`
# alone rather than a `(company_id, id)` composite.
_COMPANIES_FANOUT = DependentEndpointConfig(
    parent_name="Companies",
    resolve_param="companyId",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "company_id"},
    # Companies' own `sortBy` enum only accepts "name" - pin it explicitly rather than relying
    # on the (currently identical) implicit default.
    parent_params={"sortBy": "name", "sortOrder": "asc"},
)

VENDR_ENDPOINTS: dict[str, VendrEndpointConfig] = {
    "Companies": VendrEndpointConfig(
        name="Companies",
        path="/v1/catalog/companies",
        primary_keys=["id"],
        sort_by="name",
    ),
    "Categories": VendrEndpointConfig(
        name="Categories",
        path="/v1/catalog/categories",
        primary_keys=["id"],
        sort_by="name",
    ),
    "ProductFamilies": VendrEndpointConfig(
        name="ProductFamilies",
        path="/v1/catalog/companies/{companyId}/product-families",
        primary_keys=["id"],
        sort_by="sortOrder",
        fanout=_COMPANIES_FANOUT,
    ),
    "Products": VendrEndpointConfig(
        name="Products",
        path="/v1/catalog/companies/{companyId}/products",
        primary_keys=["id"],
        sort_by="sortOrder",
        fanout=_COMPANIES_FANOUT,
    ),
}

ENDPOINTS = tuple(VENDR_ENDPOINTS)

# No endpoint documents a server-side updated-since/created-since filter, so nothing is
# incremental — every table is a full-refresh snapshot of the current catalog.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
