from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

AUDIT_LOGS_ENDPOINT = "configuration_audit_logs"

# Tailscale keeps configuration audit logs for the most recent 90 days only.
AUDIT_LOG_RETENTION_DAYS = 90
# The audit log endpoint has no pagination, so we bound each request with a time window.
# Windows keep single responses small and give the resumable manager a checkpoint boundary.
AUDIT_LOG_WINDOW_DAYS = 7


@dataclass
class TailscaleEndpointConfig:
    name: str
    # Path relative to https://api.tailscale.com/api/v2, with a `{tailnet}` placeholder.
    path: str
    # Key wrapping the row list in the JSON response (e.g. {"devices": [...]}).
    data_key: str
    primary_key: Optional[str] = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable, immutable field to partition by. Only set where rows are immutable or the
    # field never changes after creation.
    partition_key: Optional[str] = None
    params: dict[str, str] = field(default_factory=dict)


TAILSCALE_ENDPOINTS: dict[str, TailscaleEndpointConfig] = {
    # The Tailscale API does not paginate list endpoints — each returns the full result
    # set in one response — and none of devices/users/keys accept a server-side time
    # filter, so those tables are full refresh only.
    "devices": TailscaleEndpointConfig(
        name="devices",
        path="/tailnet/{tailnet}/devices",
        data_key="devices",
        # Without `fields=all` the API omits detail fields like enabledRoutes,
        # advertisedRoutes and clientConnectivity.
        params={"fields": "all"},
    ),
    "users": TailscaleEndpointConfig(
        name="users",
        path="/tailnet/{tailnet}/users",
        data_key="users",
    ),
    "keys": TailscaleEndpointConfig(
        name="keys",
        path="/tailnet/{tailnet}/keys",
        data_key="keys",
    ),
    AUDIT_LOGS_ENDPOINT: TailscaleEndpointConfig(
        name=AUDIT_LOGS_ENDPOINT,
        path="/tailnet/{tailnet}/logging/configuration",
        data_key="logs",
        # Audit log records carry no unique identifier (eventGroupID groups several
        # records of one event), so rows are appended rather than merged.
        primary_key=None,
        incremental_fields=[
            {
                "label": "eventTime",
                "type": IncrementalFieldType.DateTime,
                "field": "eventTime",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        # Log records are immutable, so eventTime is a stable partition key.
        partition_key="eventTime",
    ),
}

ENDPOINTS = tuple(TAILSCALE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TAILSCALE_ENDPOINTS.items()
}
