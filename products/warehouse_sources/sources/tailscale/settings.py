from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

AUDIT_LOGS_ENDPOINT = "configuration_audit_logs"
NETWORK_LOGS_ENDPOINT = "network_flow_logs"
SERVICES_ENDPOINT = "services"
SERVICE_DEVICES_ENDPOINT = "service_devices"


@dataclass(frozen=False)
class TailscaleEndpointConfig:
    name: str
    # Path relative to https://api.tailscale.com/api/v2, with a `{tailnet}` placeholder.
    path: str
    # Key wrapping the row list in the JSON response (e.g. {"devices": [...]}).
    data_key: str
    primary_keys: Optional[list[str]] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable, immutable field to partition by. Only set where rows are immutable or the
    # field never changes after creation.
    partition_key: Optional[str] = None
    params: dict[str, str] = field(default_factory=dict)
    # Log endpoints have no pagination and require inclusive `start`/`end` params, so each
    # request is bounded by a time window. Windows keep single responses small and give the
    # resumable manager a checkpoint boundary.
    time_field: Optional[str] = None
    log_window: Optional[timedelta] = None
    # How far back Tailscale keeps the logs.
    retention_days: Optional[int] = None
    # Window used by the credential probe.
    probe_window: timedelta = timedelta(hours=1)


def _datetime_incremental_field(name: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


TAILSCALE_ENDPOINTS: dict[str, TailscaleEndpointConfig] = {
    # The Tailscale API does not paginate list endpoints — each returns the full result
    # set in one response — and none of devices/users/keys/services accept a server-side
    # time filter, so those tables are full refresh only.
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
    SERVICES_ENDPOINT: TailscaleEndpointConfig(
        name=SERVICES_ENDPOINT,
        path="/tailnet/{tailnet}/services",
        data_key="vipServices",
        # Service names are unique within a tailnet; services have no other id.
        primary_keys=["name"],
    ),
    SERVICE_DEVICES_ENDPOINT: TailscaleEndpointConfig(
        name=SERVICE_DEVICES_ENDPOINT,
        path="/tailnet/{tailnet}/services/{serviceName}/devices",
        data_key="hosts",
        # Host rows are only unique within their service; the service name is added to each row.
        primary_keys=["serviceName", "stableNodeID"],
    ),
    AUDIT_LOGS_ENDPOINT: TailscaleEndpointConfig(
        name=AUDIT_LOGS_ENDPOINT,
        path="/tailnet/{tailnet}/logging/configuration",
        data_key="logs",
        # Audit log records carry no unique identifier (eventGroupID groups several
        # records of one event), so rows are appended rather than merged.
        primary_keys=None,
        incremental_fields=_datetime_incremental_field("eventTime"),
        # Log records are immutable, so eventTime is a stable partition key.
        partition_key="eventTime",
        time_field="eventTime",
        log_window=timedelta(days=7),
        retention_days=90,
    ),
    NETWORK_LOGS_ENDPOINT: TailscaleEndpointConfig(
        name=NETWORK_LOGS_ENDPOINT,
        path="/tailnet/{tailnet}/logging/network",
        data_key="logs",
        # Flow log records carry no unique identifier, so rows are appended rather than merged.
        primary_keys=None,
        # `logged` is when the Tailscale logs service recorded the message, so it only moves forward.
        incremental_fields=_datetime_incremental_field("logged"),
        partition_key="logged",
        time_field="logged",
        # Every active node reports flow records every few seconds, so windows stay short
        # to keep one response bounded on large tailnets.
        log_window=timedelta(minutes=15),
        retention_days=30,
        probe_window=timedelta(minutes=1),
    ),
}

ENDPOINTS = tuple(TAILSCALE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TAILSCALE_ENDPOINTS.items()
}
