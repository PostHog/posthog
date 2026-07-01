"""Freshdesk source settings and endpoint catalog."""

from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PER_PAGE = 100


@dataclass
class FreshdeskEndpointConfig:
    name: str
    path: str
    # Server-side incremental filter param name (e.g. "updated_since", "_updated_since").
    # ``None`` means the endpoint has no server-side timestamp filter -> full refresh only.
    updated_since_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable field used for datetime partitioning. Always a creation timestamp, never a
    # mutable field like ``updated_at`` (partitions must not rewrite on every sync).
    partition_key: Optional[str] = None
    # Extra static query params (e.g. ordering on incremental endpoints).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Key the list lives under when the response is an object rather than a bare array.
    data_key: Optional[str] = None


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Top-level Freshdesk v2 endpoints. Fan-out resources (ticket conversations, solution
# articles) are intentionally omitted from this first cut — see source.py module note.
FRESHDESK_ENDPOINTS: dict[str, FreshdeskEndpointConfig] = {
    "tickets": FreshdeskEndpointConfig(
        name="tickets",
        path="/api/v2/tickets",
        # Freshdesk caps the tickets list at ~300 pages per query. Syncing incrementally on
        # `updated_since` keeps each window small and lets the watermark advance across runs,
        # which is the documented way to page beyond that cap.
        updated_since_param="updated_since",
        default_incremental_field="updated_at",
        incremental_fields=[_datetime_incremental_field("updated_at")],
        partition_key="created_at",
        # Force ascending updated_at so the incremental watermark advances monotonically.
        extra_params={"order_by": "updated_at", "order_type": "asc"},
    ),
    "contacts": FreshdeskEndpointConfig(
        name="contacts",
        path="/api/v2/contacts",
        # Freshdesk uses the underscore-prefixed `_updated_since` on the contacts endpoint.
        updated_since_param="_updated_since",
        default_incremental_field="updated_at",
        incremental_fields=[_datetime_incremental_field("updated_at")],
        partition_key="created_at",
    ),
    "companies": FreshdeskEndpointConfig(
        name="companies",
        path="/api/v2/companies",
        partition_key="created_at",
    ),
    "agents": FreshdeskEndpointConfig(name="agents", path="/api/v2/agents"),
    "groups": FreshdeskEndpointConfig(name="groups", path="/api/v2/groups"),
    "roles": FreshdeskEndpointConfig(name="roles", path="/api/v2/roles"),
    "products": FreshdeskEndpointConfig(name="products", path="/api/v2/products"),
    "skills": FreshdeskEndpointConfig(name="skills", path="/api/v2/skills", data_key="skills"),
    "ticket_fields": FreshdeskEndpointConfig(name="ticket_fields", path="/api/v2/ticket_fields"),
    "time_entries": FreshdeskEndpointConfig(
        name="time_entries",
        path="/api/v2/time_entries",
        partition_key="created_at",
    ),
    "satisfaction_ratings": FreshdeskEndpointConfig(
        name="satisfaction_ratings",
        path="/api/v2/surveys/satisfaction_ratings",
        partition_key="created_at",
    ),
    "sla_policies": FreshdeskEndpointConfig(name="sla_policies", path="/api/v2/sla_policies"),
    "business_hours": FreshdeskEndpointConfig(name="business_hours", path="/api/v2/business_hours"),
    "canned_response_folders": FreshdeskEndpointConfig(
        name="canned_response_folders", path="/api/v2/canned_response_folders"
    ),
}

ENDPOINTS = tuple(FRESHDESK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRESHDESK_ENDPOINTS.items()
}
