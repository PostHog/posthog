from dataclasses import field
from typing import Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen


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
    date_window: bool = False
    paginated: bool = True
    rows_required: bool = True


# The visitor endpoints of events and funnels require a date range, so these tables hold a rolling window.
VISITOR_WINDOW_DAYS = 30


# Timestamp filters need account verification before they can support incremental sync.
ENDPOINTS: dict[str, SmartlookEndpoint] = {
    "event_visitors": SmartlookEndpoint(
        name="event_visitors",
        path="/api/v1/events/{eventId}/visitors",
        data_selector="visitors",
        primary_keys=("event_id", "id"),
        partition_key="firstSeen",
        date_window=True,
        paginated=False,
        rows_required=False,
        fanout=DependentEndpointConfig(
            parent_name="events",
            resolve_param="eventId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "event_id"},
            parent_params={"limit": 100},
        ),
    ),
    "events": SmartlookEndpoint(name="events", path="/api/v1/events", data_selector="events"),
    "funnel_step_visitors": SmartlookEndpoint(
        name="funnel_step_visitors",
        path="/api/v1/funnels/{funnelId}/visitors/drop-off",
        data_selector="visitors",
        primary_keys=("funnel_id", "step", "visitor_id"),
        date_window=True,
        paginated=False,
    ),
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
