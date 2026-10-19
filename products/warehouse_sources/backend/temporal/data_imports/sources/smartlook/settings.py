from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class SmartlookEndpoint:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = None
    method: Literal["GET", "POST"] = "GET"
    sort_field: str | None = None
    fanout: DependentEndpointConfig | None = None
    page_size: int = 100
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


# Timestamp filters need account verification before they can support incremental sync.
ENDPOINTS: dict[str, SmartlookEndpoint] = {
    "events": SmartlookEndpoint(name="events", path="/api/v1/events", data_selector="events"),
    "funnels": SmartlookEndpoint(name="funnels", path="/api/v1/funnels", data_selector="funnels"),
    "sessions": SmartlookEndpoint(
        name="sessions",
        path="/api/v1/sessions/search",
        data_selector="sessions",
        partition_key="startedAt",
        method="POST",
        sort_field="timeStart",
    ),
    "visitor_events": SmartlookEndpoint(
        name="visitor_events",
        path="/api/v1/visitors/{visitorId}/events",
        data_selector="events",
        primary_keys=("visitor_id", "id"),
        partition_key="startedAt",
        fanout=DependentEndpointConfig(
            parent_name="visitors",
            resolve_param="visitorId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "visitor_id"},
        ),
    ),
    "visitors": SmartlookEndpoint(
        name="visitors",
        path="/api/{api_version}/visitors/search",
        data_selector="visitors",
        partition_key="firstSeen",
        method="POST",
        sort_field="timeCreate",
    ),
}
