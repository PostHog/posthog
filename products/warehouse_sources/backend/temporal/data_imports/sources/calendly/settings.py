from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class CalendlyEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param used to scope the request to the user's organization. Every Calendly v2
    # list endpoint we sync requires this (an `organization` URI).
    scope_param: Optional[str] = "organization"
    # Stable field used for datetime partitioning. Never use `updated_at` (it changes).
    partition_key: Optional[str] = "created_at"
    # Server-side time filter param, only set where the API genuinely filters (see settings below).
    incremental_filter_param: Optional[str] = None
    # Sort value passed to keep pagination ordering stable/monotonic.
    sort: Optional[str] = None


CALENDLY_ENDPOINTS: dict[str, CalendlyEndpointConfig] = {
    "event_types": CalendlyEndpointConfig(
        name="event_types",
        path="/event_types",
    ),
    # The only endpoint with a real server-side timestamp filter (`min_start_time`). It filters on
    # `start_time` (the scheduled meeting time), so incremental syncs advance on `start_time`, not on
    # created/updated. Late-created events with a `start_time` below the watermark can be missed; the
    # merge dedupes on `uri` for everything re-fetched. Partitioning stays on the stable `created_at`.
    "scheduled_events": CalendlyEndpointConfig(
        name="scheduled_events",
        path="/scheduled_events",
        incremental_filter_param="min_start_time",
        sort="start_time:asc",
        incremental_fields=[
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "groups": CalendlyEndpointConfig(
        name="groups",
        path="/groups",
    ),
    "organization_memberships": CalendlyEndpointConfig(
        name="organization_memberships",
        path="/organization_memberships",
    ),
    "routing_forms": CalendlyEndpointConfig(
        name="routing_forms",
        path="/routing_forms",
    ),
}

ENDPOINTS = tuple(CALENDLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CALENDLY_ENDPOINTS.items()
}
