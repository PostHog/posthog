"""RevenueCat API v2 endpoint catalog.

Reference: https://www.revenuecat.com/docs/api-v2

Every list endpoint here uses cursor pagination (`starting_after` / `next_page`),
defaulted to `limit=100`. Field names match the RevenueCat response payloads
verbatim, except each endpoint's partition timestamp field which is normalized
from milliseconds to Unix seconds during iteration (see ``_ms_to_seconds`` in
``revenuecat.py``). The partition key pins to that normalized field — it's stable
per row and never rewritten, so partitioning by it never re-shuffles data.

Note the partition field is not uniform across endpoints: the customer object
has no ``created_at`` — it exposes ``first_seen_at`` (the stable first-seen
timestamp) instead — while the dashboard-configured resources (products,
entitlements, offerings, apps) carry ``created_at``.
"""

from typing import NamedTuple

from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    APP_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    ENTITLEMENT_RESOURCE_NAME,
    EVENT_RESOURCE_NAME,
    OFFERING_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
)


class RevenueCatEndpoint(NamedTuple):
    """Single RevenueCat API v2 list endpoint.

    `path_suffix` is appended to `/projects/{project_id}` — every list endpoint we
    sync from is project-scoped. `partition_keys` must be stable for the lifetime
    of a row (never `updated_at` / `last_seen_at`); ``created_at`` (or
    ``first_seen_at`` for customers), normalized from RevenueCat's ms representation
    to Unix seconds, satisfies that requirement.
    """

    path_suffix: str
    primary_keys: list[str]
    partition_keys: list[str]


# All endpoints we expose as warehouse tables from the REST API. RevenueCat's
# customer subscriptions/purchases live under per-customer paths (which would
# require a fan-out) — those are intentionally omitted here in favor of the
# realtime webhook events table, which captures the same activity per-purchase
# without needing to iterate every customer on every sync.
REVENUECAT_API_ENDPOINTS: dict[str, RevenueCatEndpoint] = {
    CUSTOMER_RESOURCE_NAME: RevenueCatEndpoint(
        path_suffix="/customers",
        primary_keys=["id"],
        # The customer object has no `created_at`; `first_seen_at` is its stable
        # creation-time timestamp (`last_seen_at` is rewritten, so unsuitable).
        partition_keys=["first_seen_at"],
    ),
    PRODUCT_RESOURCE_NAME: RevenueCatEndpoint(
        path_suffix="/products",
        primary_keys=["id"],
        partition_keys=["created_at"],
    ),
    ENTITLEMENT_RESOURCE_NAME: RevenueCatEndpoint(
        path_suffix="/entitlements",
        primary_keys=["id"],
        partition_keys=["created_at"],
    ),
    OFFERING_RESOURCE_NAME: RevenueCatEndpoint(
        path_suffix="/offerings",
        primary_keys=["id"],
        partition_keys=["created_at"],
    ),
    APP_RESOURCE_NAME: RevenueCatEndpoint(
        path_suffix="/apps",
        primary_keys=["id"],
        partition_keys=["created_at"],
    ),
}

REVENUECAT_API_SCHEMA_NAMES: tuple[str, ...] = tuple(REVENUECAT_API_ENDPOINTS.keys())

# Webhook-only schemas. We expose a single `events` table that captures every
# RevenueCat webhook event regardless of type — events share a flat shape and
# querying them in one table is more ergonomic than fanning out per-type tables.
REVENUECAT_WEBHOOK_SCHEMA_NAMES: tuple[str, ...] = (EVENT_RESOURCE_NAME,)
