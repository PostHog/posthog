from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Recharge caps page size at 250 (default 50). Larger pages mean fewer
# round-trips against the leaky-bucket rate limit (40 burst, ~2 req/s sustained).
DEFAULT_PAGE_SIZE = 250

# `payment_methods` is an expensive endpoint: a full 250-record page consistently
# exceeds the 60s read timeout (the server can't generate the page in time),
# surfacing as upstream read timeouts. Request smaller pages so each response
# returns well within the timeout.
PAYMENT_METHODS_PAGE_SIZE = 50


@dataclass
class RechargeEndpointConfig:
    """Declarative metadata for a single Recharge list endpoint.

    `path` is appended to the API base URL. `partition_key` must be a STABLE
    field (`created_at`) so partitions are never rewritten — never `updated_at`.
    `incremental_fields` is the menu of advertised cursor options; the user's
    actual choice arrives via `inputs.incremental_field`.

    `supports_incremental` is only `True` for endpoints where Recharge exposes a
    server-side `updated_at_min` / `created_at_min` filter (per the public
    2021-11 API docs). Endpoints without a confirmed server-side timestamp filter
    ship full-refresh only.
    """

    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = "created_at"
    supports_incremental: bool = True
    # Whether the list endpoint accepts a `sort_by` query param. The 2021-11 API
    # dropped `sort_by` for `/products` (it isn't in the sorting reference for
    # this version), so sending it returns a 422. Endpoints without sort support
    # rely on cursor pagination for ordering instead.
    supports_sort: bool = True
    # Default sort field used when not syncing incrementally. Recharge accepts
    # `<field>-asc` / `<field>-desc`; `id-asc` is a stable monotonic order that
    # avoids page-boundary skips/dupes when rows are inserted mid-sync.
    default_sort_field: str = "id"
    # Records requested per page. Capped at 250 by Recharge; lower it for
    # endpoints whose pages are too slow to generate within the read timeout.
    page_size: int = DEFAULT_PAGE_SIZE


def _timestamp_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Both `updated_at` and `created_at` are offered as incremental cursors for the
# endpoints that support server-side timestamp filtering. `updated_at` is the
# better default (catches mutations); `created_at` suits append-only consumers.
_UPDATED_AND_CREATED = [_timestamp_field("updated_at"), _timestamp_field("created_at")]


RECHARGE_ENDPOINTS: dict[str, RechargeEndpointConfig] = {
    "customers": RechargeEndpointConfig(
        name="customers",
        path="/customers",
        incremental_fields=_UPDATED_AND_CREATED,
    ),
    "subscriptions": RechargeEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
        incremental_fields=_UPDATED_AND_CREATED,
    ),
    "orders": RechargeEndpointConfig(
        name="orders",
        path="/orders",
        incremental_fields=_UPDATED_AND_CREATED,
    ),
    "charges": RechargeEndpointConfig(
        name="charges",
        path="/charges",
        incremental_fields=_UPDATED_AND_CREATED,
    ),
    "addresses": RechargeEndpointConfig(
        name="addresses",
        path="/addresses",
        incremental_fields=_UPDATED_AND_CREATED,
    ),
    "discounts": RechargeEndpointConfig(
        name="discounts",
        path="/discounts",
        incremental_fields=_UPDATED_AND_CREATED,
    ),
    "onetimes": RechargeEndpointConfig(
        name="onetimes",
        path="/onetimes",
        incremental_fields=_UPDATED_AND_CREATED,
    ),
    # `/products` on the 2021-11 API only accepts cursor pagination + `limit`/
    # `ids` — unlike 2021-01 it exposes neither `sort_by` nor a `*_min` timestamp
    # filter, so sending either returns a 422. Full-refresh, cursor-ordered only.
    "products": RechargeEndpointConfig(
        name="products",
        path="/products",
        incremental_fields=[],
        supports_incremental=False,
        supports_sort=False,
    ),
    "payment_methods": RechargeEndpointConfig(
        name="payment_methods",
        path="/payment_methods",
        incremental_fields=_UPDATED_AND_CREATED,
        page_size=PAYMENT_METHODS_PAGE_SIZE,
    ),
    # Collections expose `created_at`/`updated_at` on the object but the list
    # endpoint's server-side timestamp filtering is not documented as reliably
    # as the core resources, so ship full-refresh and partition by created_at.
    "collections": RechargeEndpointConfig(
        name="collections",
        path="/collections",
        incremental_fields=[],
        supports_incremental=False,
    ),
}

ENDPOINTS = tuple(RECHARGE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RECHARGE_ENDPOINTS.items() if config.supports_incremental
}
