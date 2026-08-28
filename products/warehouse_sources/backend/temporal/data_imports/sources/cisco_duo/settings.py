from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Duo Admin API endpoints come in three shapes:
#   "log_v2"  -> /admin/v2/logs/* : mintime/maxtime window (ms) + opaque `next_offset` cursor,
#                wrapped response ({"response": {<data_key>: [...], "metadata": {...}}}).
#   "log_v1"  -> /admin/v1/logs/* : `mintime` (seconds) only, plain list response capped at
#                1000 records per call; paginate by advancing mintime.
#   "list_v1" -> /admin/v1/* resource lists: limit/offset pagination with an integer
#                `next_offset` in the top-level response metadata.
ApiStyle = Literal["log_v2", "log_v1", "list_v1"]


def _integer_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.Integer,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class CiscoDuoEndpointConfig:
    name: str
    path: str
    api_style: ApiStyle
    # None for administrator_logs: the v1 admin log has no unique event id, so it is
    # append-only and never merged.
    primary_keys: Optional[list[str]] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The timestamp field on returned rows that maps to the mintime/maxtime request params.
    # "timestamp" is unix seconds (int); "ts" is an ISO-8601 string.
    timestamp_field: Optional[str] = None
    # Key holding the row list inside the v2 wrapped response ("authlogs" or "items").
    data_key: Optional[str] = None
    # Stable, immutable field to partition by (log timestamps and `created` never mutate).
    partition_key: Optional[str] = None
    partition_format: Literal["month", "week", "day", "hour"] = "week"
    # Fields stripped from every row before it is yielded — used to keep credentials the API
    # returns (e.g. an integration's secret_key) out of the warehouse table.
    redact_fields: Optional[list[str]] = None
    description: Optional[str] = None


# First-sync window for the v2 log endpoints: Duo rejects a mintime older than its
# retention horizon (about 180 days on most editions), so reach back exactly that far.
DEFAULT_LOOKBACK_DAYS = 180

CISCO_DUO_ENDPOINTS: dict[str, CiscoDuoEndpointConfig] = {
    "authentication_logs": CiscoDuoEndpointConfig(
        name="authentication_logs",
        path="/admin/v2/logs/authentication",
        api_style="log_v2",
        primary_keys=["txid"],
        incremental_fields=[_integer_incremental_field("timestamp")],
        timestamp_field="timestamp",
        data_key="authlogs",
        partition_key="timestamp",
        description=f"Only syncs the last {DEFAULT_LOOKBACK_DAYS} days on initial sync",
    ),
    "administrator_logs": CiscoDuoEndpointConfig(
        name="administrator_logs",
        path="/admin/v1/logs/administrator",
        api_style="log_v1",
        primary_keys=None,
        incremental_fields=[_integer_incremental_field("timestamp")],
        timestamp_field="timestamp",
        partition_key="timestamp",
        description="Administrator log events have no unique id, so this table is append-only",
    ),
    "telephony_logs": CiscoDuoEndpointConfig(
        name="telephony_logs",
        path="/admin/v2/logs/telephony",
        api_style="log_v2",
        primary_keys=["telephony_id"],
        incremental_fields=[_datetime_incremental_field("ts")],
        timestamp_field="ts",
        data_key="items",
        partition_key="ts",
        description=f"Only syncs the last {DEFAULT_LOOKBACK_DAYS} days on initial sync",
    ),
    "activity_logs": CiscoDuoEndpointConfig(
        name="activity_logs",
        path="/admin/v2/logs/activity",
        api_style="log_v2",
        primary_keys=["activity_id"],
        incremental_fields=[_datetime_incremental_field("ts")],
        timestamp_field="ts",
        data_key="items",
        partition_key="ts",
        description=f"Only syncs the last {DEFAULT_LOOKBACK_DAYS} days on initial sync",
    ),
    # The v1 resource lists have no server-side time filter, so they are full-refresh only.
    "users": CiscoDuoEndpointConfig(
        name="users",
        path="/admin/v1/users",
        api_style="list_v1",
        primary_keys=["user_id"],
        partition_key="created",
        partition_format="month",
    ),
    "groups": CiscoDuoEndpointConfig(
        name="groups",
        path="/admin/v1/groups",
        api_style="list_v1",
        primary_keys=["group_id"],
    ),
    "phones": CiscoDuoEndpointConfig(
        name="phones",
        path="/admin/v1/phones",
        api_style="list_v1",
        primary_keys=["phone_id"],
    ),
    "admins": CiscoDuoEndpointConfig(
        name="admins",
        path="/admin/v1/admins",
        api_style="list_v1",
        primary_keys=["admin_id"],
    ),
    "integrations": CiscoDuoEndpointConfig(
        name="integrations",
        path="/admin/v1/integrations",
        api_style="list_v1",
        primary_keys=["integration_key"],
        # The integrations list returns each integration's secret_key; never persist it — a
        # project member who can read this table could otherwise sign requests as any integration.
        redact_fields=["secret_key"],
    ),
}

ENDPOINTS = tuple(CISCO_DUO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CISCO_DUO_ENDPOINTS.items()
}
