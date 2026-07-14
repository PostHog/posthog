from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["cursor", "offset", "none"]

_BOOKING_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updatedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class CalComEndpointConfig:
    name: str
    path: str
    # Value for the `cal-api-version` header. Cal.com versions endpoints individually; omitting the
    # header silently falls back to a legacy behavior, so it must be pinned per endpoint.
    api_version: Optional[str] = None
    pagination: PaginationStyle = "none"
    # `/me` returns a single object under `data` instead of a list.
    single_object: bool = False
    # Cal.com numeric ids are unique per resource type across the account, so `id` is a safe key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning (never an updated-at style field).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental field name to the server-side query param that filters on it.
    incremental_param_by_field: dict[str, str] = field(default_factory=dict)
    default_incremental_field: Optional[str] = None


# Cal.com API v2 list endpoints (https://cal.com/docs/api-reference/v2/introduction). Only bookings
# exposes server-side timestamp filters (afterUpdatedAt / afterCreatedAt), so it is the only
# incremental-capable endpoint; the rest are small, unpaginated catalogs synced via full refresh.
CAL_COM_ENDPOINTS: dict[str, CalComEndpointConfig] = {
    "bookings": CalComEndpointConfig(
        name="bookings",
        path="/bookings",
        api_version="2026-05-01",
        pagination="cursor",
        partition_key="createdAt",
        incremental_fields=_BOOKING_INCREMENTAL_FIELDS,
        incremental_param_by_field={
            "updatedAt": "afterUpdatedAt",
            "createdAt": "afterCreatedAt",
        },
        default_incremental_field="updatedAt",
    ),
    "event_types": CalComEndpointConfig(
        name="event_types",
        path="/event-types",
        api_version="2024-06-14",
    ),
    "schedules": CalComEndpointConfig(
        name="schedules",
        path="/schedules",
        api_version="2024-06-11",
    ),
    "teams": CalComEndpointConfig(
        name="teams",
        path="/teams",
    ),
    "webhooks": CalComEndpointConfig(
        name="webhooks",
        path="/webhooks",
        pagination="offset",
    ),
    "me": CalComEndpointConfig(
        name="me",
        path="/me",
        single_object=True,
    ),
}

ENDPOINTS = tuple(CAL_COM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CAL_COM_ENDPOINTS.items() if config.incremental_fields
}
