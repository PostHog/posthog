from dataclasses import field
from datetime import UTC, datetime

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

REGION_HOSTS = {
    "global": "api.meraki.com",
    "canada": "api.meraki.ca",
    "china": "api.meraki.cn",
    "india": "api.meraki.in",
    "us_government": "api.gov-meraki.com",
}

# The maximum lookback that the network clients endpoint accepts (31 days).
CLIENTS_TIMESPAN_SECONDS = 31 * 24 * 60 * 60

# Client usage histories hold one row per client per day. An incremental read always covers at least one day, so
# it reads the current day again.
CLIENT_USAGE_MIN_TIMESPAN_SECONDS = 24 * 60 * 60

# The uplink usage history endpoint accepts a lookback of 30 days at most.
UPLINK_USAGE_MAX_TIMESPAN_SECONDS = 30 * 24 * 60 * 60
UPLINK_USAGE_RESOLUTION_SECONDS = 60 * 60
# An incremental read covers at least two intervals, so it reads the current partial hour again.
UPLINK_USAGE_MIN_TIMESPAN_SECONDS = 2 * UPLINK_USAGE_RESOLUTION_SECONDS

# Client keys go into the query string, so a request names a bounded number of clients.
CLIENT_USAGE_BATCH_SIZE = 100

# Product types that the network events endpoint accepts. A network can contain others, such as sensor.
EVENT_PRODUCT_TYPES = frozenset(
    {
        "appliance",
        "camera",
        "campusGateway",
        "cellularGateway",
        "secureConnect",
        "switch",
        "systemsManager",
        "wireless",
        "wirelessController",
    }
)

# The official Meraki SDK stops an event log walk at this date, which is older than any Meraki event.
EVENT_LOG_FLOOR = datetime(2014, 1, 1, tzinfo=UTC)

# Devices can upload events after the previous sync read past them.
EVENTS_LOOKBACK_SECONDS = 60 * 60


@frozen
class MerakiEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    page_size: int = 1000
    data_selector: str = "$"
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    paginated: bool = True
    partition_key: str | None = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


_NETWORK_FANOUT_PARENT = "networks"

ENDPOINTS = {
    endpoint.name: endpoint
    for endpoint in (
        MerakiEndpoint(name="networks", path="organizations/{organization_id}/networks", primary_keys=("id",)),
        MerakiEndpoint(name="devices", path="organizations/{organization_id}/devices", primary_keys=("serial",)),
        MerakiEndpoint(
            name="inventory_devices",
            path="organizations/{organization_id}/inventory/devices",
            primary_keys=("serial",),
        ),
        MerakiEndpoint(
            name="uplink_statuses", path="organizations/{organization_id}/uplinks/statuses", primary_keys=("serial",)
        ),
        MerakiEndpoint(
            name="assurance_alerts",
            path="organizations/{organization_id}/assurance/alerts",
            primary_keys=("id",),
            page_size=300,
        ),
        MerakiEndpoint(
            name="device_availabilities",
            path="organizations/{organization_id}/devices/availabilities",
            primary_keys=("serial",),
        ),
        MerakiEndpoint(
            name="network_clients",
            path="networks/{networkId}/clients",
            # Client ids are unique within a network only.
            primary_keys=("networkId", "id"),
            fanout=DependentEndpointConfig(
                parent_name=_NETWORK_FANOUT_PARENT,
                resolve_param="networkId",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "networkId"},
                child_params={"timespan": CLIENTS_TIMESPAN_SECONDS},
            ),
        ),
        MerakiEndpoint(
            name="network_events",
            # Networks with more than one product type reject event requests that omit the product type.
            path="networks/{networkId}/events?productType={productType}",
            # Events carry no identifier, so the source derives `id` from the event content.
            primary_keys=("id",),
            data_selector="events",
            fanout=DependentEndpointConfig(
                parent_name=_NETWORK_FANOUT_PARENT,
                resolve_param="networkId",
                resolve_field="id",
                include_from_parent=["productType"],
                parent_field_renames={"productType": "productType"},
                child_params={
                    "productType": {"type": "resolve", "resource": _NETWORK_FANOUT_PARENT, "field": "productType"}
                },
            ),
            incremental_fields=[_datetime_field("occurredAt")],
            default_incremental_field="occurredAt",
            partition_key="occurredAt",
        ),
        MerakiEndpoint(
            name="uplink_usage_history",
            path="networks/{networkId}/appliance/uplinks/usageHistory",
            primary_keys=("networkId", "startTime"),
            paginated=False,
            fanout=DependentEndpointConfig(
                parent_name=_NETWORK_FANOUT_PARENT,
                resolve_param="networkId",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "networkId"},
                parent_params={"perPage": 1000},
                child_params={"resolution": UPLINK_USAGE_RESOLUTION_SECONDS},
            ),
            incremental_fields=[_datetime_field("startTime")],
            default_incremental_field="startTime",
            partition_key="startTime",
        ),
        MerakiEndpoint(
            name="client_usage_histories",
            path="networks/{networkId}/clients/usageHistories",
            primary_keys=("networkId", "clientId", "ts"),
            # Each request names a batch of clients from the network clients table, so the source reads it itself.
            fanout=DependentEndpointConfig(
                parent_name=_NETWORK_FANOUT_PARENT,
                resolve_param="networkId",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "networkId"},
            ),
            incremental_fields=[_datetime_field("ts")],
            default_incremental_field="ts",
            partition_key="ts",
        ),
    )
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items() if endpoint.incremental_fields
}

AUTH_ERROR = "Cisco Meraki rejected your API key. Check the key and selected region."
PERMISSION_ERROR = (
    "Your API key cannot read this resource. Check your Meraki administrator permissions and organization ID."
)
NOT_FOUND_ERROR = "Cisco Meraki could not find this resource. Check your organization ID and selected region."
REGION_ERROR = "Select a supported Cisco Meraki region."
ORGANIZATION_ERROR = "Enter a valid Meraki organization ID. Use only letters, numbers, underscores, or hyphens."
