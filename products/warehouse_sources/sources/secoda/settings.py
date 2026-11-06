from dataclasses import field

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen


@frozen
class SecodaEndpointConfig:
    name: str
    path: str
    # Secoda resource identifiers are workspace-unique UUIDs, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Top-level keys removed from every row before it reaches the warehouse.
    drop_fields: tuple[str, ...] = ()
    fanout: DependentEndpointConfig | None = None
    # Read by the shared fan-out helper. Secoda list endpoints take no page-size param, so
    # page_size is never sent, and every endpoint is full refresh.
    page_size: int = 0
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


# Secoda v1 REST list endpoints. All are full-refresh only: Secoda's List Resources filter supports
# only exact/contains/in operators (no greater-than / on-or-after), so there is no server-side
# timestamp cursor to advance an incremental sync (see the implementing-warehouse-sources skill).
SECODA_ENDPOINTS: dict[str, SecodaEndpointConfig] = {
    "tables": SecodaEndpointConfig(name="tables", path="/api/v1/table/tables"),
    "columns": SecodaEndpointConfig(name="columns", path="/api/v1/table/columns"),
    "collections": SecodaEndpointConfig(name="collections", path="/api/v1/collection/collections"),
    "users": SecodaEndpointConfig(name="users", path="/api/v1/user"),
    "groups": SecodaEndpointConfig(name="groups", path="/api/v1/auth/group"),
    "tags": SecodaEndpointConfig(name="tags", path="/api/v1/tag"),
    "databases": SecodaEndpointConfig(name="databases", path="/api/v1/database/databases"),
    "schemas": SecodaEndpointConfig(name="schemas", path="/api/v1/database/schemas"),
    # Secoda documents `credentials` as redacted, but a credentials blob has no analytical value and
    # must never land in the warehouse if that redaction ever changes.
    "integrations": SecodaEndpointConfig(
        name="integrations", path="/api/v1/integration/integrations", drop_fields=("credentials",)
    ),
    "lineage": SecodaEndpointConfig(name="lineage", path="/api/v1/lineage/manual/"),
    "monitors": SecodaEndpointConfig(name="monitors", path="/api/v1/monitor/monitors"),
    "incidents": SecodaEndpointConfig(name="incidents", path="/api/v1/monitor/incidents"),
    # Secoda requires a `monitor` (or `incident_id`) filter on this endpoint, so it fans out over monitors.
    # The filter sits in the path because the fan-out helper binds parent values only into the path;
    # monitor ids are UUIDs, so they need no escaping.
    "monitor_measurements": SecodaEndpointConfig(
        name="monitor_measurements",
        path="/api/v1/monitor/measurements?monitor={monitor}",
        primary_keys=["monitor_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="monitors",
            resolve_param="monitor",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "monitor_id"},
            # A monitor deleted between the monitors listing and its measurements fetch must not fail the sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "charts": SecodaEndpointConfig(name="charts", path="/api/v1/dashboard/charts"),
    "events": SecodaEndpointConfig(name="events", path="/api/v1/event/events"),
    "event_properties": SecodaEndpointConfig(name="event_properties", path="/api/v1/event/event_properties"),
    "event_categories": SecodaEndpointConfig(name="event_categories", path="/api/v1/event/category"),
}

ENDPOINTS = tuple(SECODA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
