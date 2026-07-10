from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Ubidots hosts vary by account tier: Industrial/enterprise accounts live on
# industrial.api.ubidots.com, legacy STEM/educational accounts on things.ubidots.com. Both expose
# the same v2.0 (metadata) and v1.6 (values) REST APIs — verified with live probes against both.
DEFAULT_UBIDOTS_API_BASE_URL = "https://industrial.api.ubidots.com"
ALLOWED_UBIDOTS_API_BASE_URLS = (
    DEFAULT_UBIDOTS_API_BASE_URL,
    "https://things.ubidots.com",
)

# Dots (values) carry a millisecond epoch `timestamp`, which is what the v1.6 values endpoints
# filter on server-side via the `start` query param.
TIMESTAMP_INCREMENTAL: IncrementalField = {
    "label": "timestamp",
    "type": IncrementalFieldType.Integer,
    "field": "timestamp",
    "field_type": IncrementalFieldType.Integer,
}


@dataclass
class UbidotsEndpointConfig:
    name: str
    path: str  # Full path including the API version prefix, e.g. "/api/v2.0/devices/"
    # Only the values endpoint filters server-side (`start`/`end` ms timestamps); v2.0 metadata
    # endpoints expose no documented monotonic update cursor, so they are full refresh only.
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# The `values` stream fans out per variable: v2.0 lists the variables, then v1.6
# /variables/{id}/values pages through each variable's time-series dots (newest first).
VALUES_ENDPOINT = "values"
VALUES_PATH_TEMPLATE = "/api/v1.6/variables/{variable_id}/values"

UBIDOTS_ENDPOINTS: dict[str, UbidotsEndpointConfig] = {
    "devices": UbidotsEndpointConfig(name="devices", path="/api/v2.0/devices/"),
    "variables": UbidotsEndpointConfig(name="variables", path="/api/v2.0/variables/"),
    "device_groups": UbidotsEndpointConfig(name="device_groups", path="/api/v2.0/device_groups/"),
    "device_types": UbidotsEndpointConfig(name="device_types", path="/api/v2.0/device_types/"),
    "events": UbidotsEndpointConfig(name="events", path="/api/v2.0/events/"),
    VALUES_ENDPOINT: UbidotsEndpointConfig(
        name=VALUES_ENDPOINT,
        path=VALUES_PATH_TEMPLATE,
        supports_incremental=True,
        incremental_fields=[TIMESTAMP_INCREMENTAL],
        # A variable stores at most one dot per millisecond timestamp (writing the same timestamp
        # overwrites), but timestamps repeat across variables — the parent id keeps the key unique
        # table-wide.
        primary_keys=["variable", "timestamp"],
    ),
}

ENDPOINTS = tuple(UBIDOTS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in UBIDOTS_ENDPOINTS.items()
}
