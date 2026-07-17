from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class FreshsalesEndpointConfig:
    name: str
    # API resource segment, e.g. "contacts" -> /crm/sales/api/contacts/...
    resource: str
    # Top-level array key in the JSON response envelope (Freshsales pluralizes the object name).
    object_key: str
    # View-based objects (contacts, deals, ...) must resolve a "view" id via /<resource>/filters
    # before they can be listed. Direct-list objects (tasks, appointments, ...) are queried directly.
    requires_view: bool = False
    # Static query params sent on every request (e.g. {"filter": "open"} for tasks).
    params: dict[str, str] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field for datetime partitioning. Only set where the field is confirmed present
    # and immutable (never updated_at).
    partition_key: Optional[str] = None
    # Sort field to request for stable pagination. Only set on endpoints that support `sort`.
    sort: Optional[str] = None
    # Some objects (notably leads) don't exist on every Freshsales account; a 404 means "skip", not "fail".
    tolerate_missing: bool = False
    # Incremental sync is full-refresh only for now (see note below), so this stays empty for every
    # endpoint. Kept as the source of truth so enabling incremental later is a settings-only change.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Freshsales has no reliably paginated server-side timestamp filter: the only updated_at filter
# (POST /filtered_search) silently drops custom fields and has undocumented pagination, so every
# endpoint ships as full refresh (matching Airbyte's Freshsales connector). The view/scroll list
# APIs return complete records but offer no server-side incremental cutoff.
FRESHSALES_ENDPOINTS: dict[str, FreshsalesEndpointConfig] = {
    "contacts": FreshsalesEndpointConfig(
        name="contacts",
        resource="contacts",
        object_key="contacts",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
    ),
    "sales_accounts": FreshsalesEndpointConfig(
        name="sales_accounts",
        resource="sales_accounts",
        object_key="sales_accounts",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
    ),
    "deals": FreshsalesEndpointConfig(
        name="deals",
        resource="deals",
        object_key="deals",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
    ),
    "leads": FreshsalesEndpointConfig(
        name="leads",
        resource="leads",
        object_key="leads",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
        # Many newer "contacts-based" Freshsales accounts have no separate leads object.
        tolerate_missing=True,
    ),
    "sales_activities": FreshsalesEndpointConfig(
        name="sales_activities",
        resource="sales_activities",
        object_key="sales_activities",
    ),
    "open_tasks": FreshsalesEndpointConfig(
        name="open_tasks",
        resource="tasks",
        object_key="tasks",
        params={"filter": "open"},
    ),
    "completed_tasks": FreshsalesEndpointConfig(
        name="completed_tasks",
        resource="tasks",
        object_key="tasks",
        params={"filter": "completed"},
    ),
    "past_appointments": FreshsalesEndpointConfig(
        name="past_appointments",
        resource="appointments",
        object_key="appointments",
        params={"filter": "past"},
    ),
    "upcoming_appointments": FreshsalesEndpointConfig(
        name="upcoming_appointments",
        resource="appointments",
        object_key="appointments",
        params={"filter": "upcoming"},
    ),
}

ENDPOINTS = tuple(FRESHSALES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRESHSALES_ENDPOINTS.items()
}
