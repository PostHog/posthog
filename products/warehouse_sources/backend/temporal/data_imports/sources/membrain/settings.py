from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class MembrainEndpointConfig:
    name: str
    # Path under `https://{subdomain}.membrain.com/API/v2` (the documented paths all end in `/`).
    path: str
    # Paged endpoints return a `{count, from, to, items: [...]}` envelope and accept `?From=N`;
    # the rest return a bare JSON array in one response.
    paged: bool = False
    # Whether the endpoint's reference documents `SortBy` ('CreatedDate ASC' etc). Only
    # companies, contacts and activities do; the other paged endpoints don't document it, so we
    # don't send it there and their page order follows the API's default.
    supports_sort_by: bool = False
    # Documented query params sent on every request (e.g. IncludeDeleted, so deletions reach the
    # warehouse instead of rows silently disappearing from the sync).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Stable creation timestamp used for datetime partitioning. Never a Changed* field, which
    # would rewrite partitions on every update.
    partition_key: str | None = None
    # Membrain ids are GUIDs in a PascalCase `Id` field, unique per entity type, and each
    # endpoint maps to its own table.
    primary_keys: list[str] = field(default_factory=lambda: ["Id"])


# Membrain REST API v2 endpoints (https://www.membrain.com/developers/api-documentation).
# `opportunities` are Membrain's Sales Projects and `account_growth_items` its Account Growth
# projects; the schema names follow the API paths so they match what the reference documents.
MEMBRAIN_ENDPOINTS: dict[str, MembrainEndpointConfig] = {
    "companies": MembrainEndpointConfig(
        name="companies",
        path="/companies/",
        paged=True,
        supports_sort_by=True,
        extra_params={"IncludeDeleted": "true"},
        partition_key="CreatedDate",
    ),
    "contacts": MembrainEndpointConfig(
        name="contacts",
        path="/contacts/",
        paged=True,
        supports_sort_by=True,
        extra_params={"IncludeDeleted": "true", "IncludeRetired": "true"},
        partition_key="CreatedDate",
    ),
    "prospects": MembrainEndpointConfig(
        name="prospects",
        path="/prospects/",
        paged=True,
        partition_key="CreatedDate",
    ),
    "opportunities": MembrainEndpointConfig(
        name="opportunities",
        path="/opportunities/",
        paged=True,
        partition_key="CreatedDate",
    ),
    "account_growth_items": MembrainEndpointConfig(
        name="account_growth_items",
        path="/accountGrowthItems/",
        paged=True,
        partition_key="CreatedDate",
    ),
    "tickets": MembrainEndpointConfig(
        name="tickets",
        path="/tickets/",
        paged=True,
        partition_key="CreatedDate",
    ),
    "activities": MembrainEndpointConfig(
        name="activities",
        path="/activities/",
        paged=True,
        supports_sort_by=True,
        partition_key="CreatedDate",
    ),
    "users": MembrainEndpointConfig(name="users", path="/users/"),
    "roles": MembrainEndpointConfig(name="roles", path="/roles/"),
    # `/customFields/` returns one object holding a per-entity array of field definitions
    # (companyCustomFields, contactCustomFields, ...); the transport flattens it into one row per
    # definition with an `EntityType` column, so the composite key covers a definition that
    # appears under more than one entity.
    "custom_fields": MembrainEndpointConfig(
        name="custom_fields",
        path="/customFields/",
        primary_keys=["EntityType", "Id"],
    ),
    "products": MembrainEndpointConfig(name="products", path="/products/"),
}

ENDPOINTS = tuple(MEMBRAIN_ENDPOINTS.keys())

# All endpoints are full refresh only for now. The main list endpoints do document server-side
# ChangedFromDate/ChangedToDate and CreatedFromDate/CreatedToDate range filters (both ends of a
# range must be provided together), but the reference is the only evidence available: the filters
# could not be verified against a live instance here (no credentials), and four of the paged
# endpoints (prospects, opportunities, accountGrowthItems, tickets) document no SortBy, so row
# order inside a window is unknown. Enabling incremental is a matter of populating this dict,
# mapping the user's cursor into the range params in `membrain.py`, and passing an explicit upper
# bound, once the filters are verified live.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
