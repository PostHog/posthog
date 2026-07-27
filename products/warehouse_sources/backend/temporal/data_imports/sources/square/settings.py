from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class SquareEndpointConfig:
    name: str
    path: str
    # Top-level key in the JSON response that holds the list of rows
    # (e.g. `{"payments": [...]}` -> `"payments"`). Catalog uses `"objects"`.
    data_key: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for partitioning. Must never change for a row
    # (so `created_at`, never `updated_at`). `None` disables partitioning.
    partition_key: Optional[str] = None
    # Name of the server-side timestamp filter query param (e.g. `begin_time`).
    # Only set when the API genuinely filters on it — this is what enables
    # incremental sync. `None` => full refresh only.
    time_filter_param: Optional[str] = None
    # Whether the endpoint uses cursor pagination. `/v2/locations` returns every
    # row in a single response with no cursor.
    paginated: bool = True
    # Static query params applied to every request (sort order, catalog types, ...).
    extra_params: dict[str, str] = field(default_factory=dict)


def _created_at_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Endpoints are deliberately limited to the GET, cursor-paginated resources that
# work with a single Personal Access Token and no per-location fan-out. Orders,
# Invoices, Inventory and Team members all require POST `/search` calls scoped to
# `location_ids`, so they're intentionally left out of this alpha implementation.
SQUARE_ENDPOINTS: dict[str, SquareEndpointConfig] = {
    # Payments and Refunds expose `begin_time`, a server-side filter on `created_at`,
    # so they support incremental sync. Square sorts these DESC by default; we force
    # ASC so the pipeline's cursor watermark advances correctly.
    "payments": SquareEndpointConfig(
        name="payments",
        path="/v2/payments",
        data_key="payments",
        primary_keys=["id"],
        partition_key="created_at",
        time_filter_param="begin_time",
        incremental_fields=_created_at_incremental_field(),
        extra_params={"sort_order": "ASC"},
    ),
    "refunds": SquareEndpointConfig(
        name="refunds",
        path="/v2/refunds",
        data_key="refunds",
        primary_keys=["id"],
        partition_key="created_at",
        time_filter_param="begin_time",
        incremental_fields=_created_at_incremental_field(),
        extra_params={"sort_order": "ASC"},
    ),
    # `GET /v2/customers` has no server-side `created_at`/`updated_at` filter (only
    # the POST `/v2/customers/search` endpoint does), so this is full refresh. We
    # still sort by CREATED_AT ASC for stable pagination.
    "customers": SquareEndpointConfig(
        name="customers",
        path="/v2/customers",
        data_key="customers",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[],
        extra_params={"sort_field": "CREATED_AT", "sort_order": "ASC"},
    ),
    # Locations returns every location in one response — no cursor, no time filter.
    "locations": SquareEndpointConfig(
        name="locations",
        path="/v2/locations",
        data_key="locations",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[],
        paginated=False,
    ),
    # Catalog objects (items, categories, taxes, ...) only carry `updated_at`, not
    # `created_at`, so there's no stable partition key — partitioning is disabled.
    # `GET /v2/catalog/list` has no time filter, so it's full refresh.
    "catalog": SquareEndpointConfig(
        name="catalog",
        path="/v2/catalog/list",
        data_key="objects",
        primary_keys=["id"],
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(SQUARE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SQUARE_ENDPOINTS.items()
}
