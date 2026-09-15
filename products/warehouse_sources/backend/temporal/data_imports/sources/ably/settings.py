from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://main.realtime.ably.net"

# Ably caps page size at 1000 (default 100) on /stats, /channels, history and presence.
MAX_LIMIT = 1000

# https://ably.com/docs/api/rest-api#stats
STATS_UNITS = ("minute", "hour", "day", "month")
DEFAULT_STATS_UNIT = "hour"

# `by=value` makes `/channels` return `ChannelDetails` objects instead of bare name strings.
# The details are what the table is worth syncing for, and the fan-out reads `channelId` from
# them.
CHANNEL_LIST_PARAMS = {"by": "value"}

# Every channel-scoped endpoint hangs off `/channels/{channel_id}/...`, so the channel
# enumeration is the parent they fan out from. `channel_path` is the percent-encoded name that
# `_add_channel_path` in ably.py derives, because Ably channel names can contain `/` and `:`.
CHANNEL_FANOUT = DependentEndpointConfig(
    parent_name="Channels",
    resolve_param="channel_id",
    resolve_field="channel_path",
    include_from_parent=["channelId"],
    parent_field_renames={"channelId": "channel_id"},
    parent_params=CHANNEL_LIST_PARAMS,
)


@frozen
class AblyEndpointConfig:
    name: str
    path: str
    table_name: str
    params: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = MAX_LIMIT
    sort_mode: Literal["asc", "desc"] = "asc"
    fanout: DependentEndpointConfig | None = None


ABLY_ENDPOINTS: dict[str, AblyEndpointConfig] = {
    "Stats": AblyEndpointConfig(
        name="Stats",
        path="/stats",
        table_name="stats",
        # `direction=forwards` because Ably's stats and history endpoints both default to
        # newest-first, which would walk the incremental watermark backwards.
        params={"direction": "forwards"},
        # `interval_start_ms` (Unix ms) is derived from `intervalId` (see `_add_interval_start` in
        # ably.py) because Ably's own `intervalId` is a granularity-dependent string
        # ("2024-01-15:14:05" for minute, "2024-01-15:14" for hour, etc), not directly usable as
        # the `start`/`end` stats params, which take Unix ms. Using the same unit here means the
        # watermark from one sync feeds straight back into the next sync's `start` param with no
        # reformatting.
        incremental_fields=[
            {
                "label": "Interval start",
                "type": IncrementalFieldType.DateTime,
                "field": "interval_start_ms",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        default_incremental_field="interval_start_ms",
        # `interval_start` (ISO datetime string, also derived from `intervalId`) is used for
        # partitioning instead of `interval_start_ms`, because partitioning wants an actual
        # datetime-typed column.
        partition_key="interval_start",
        # `intervalId` is unique within a single granularity (`unit`), but the source only ever
        # syncs one selected unit at a time. `unit` is included defensively in case that changes.
        primary_key=["unit", "intervalId"],
    ),
    "Channels": AblyEndpointConfig(
        name="Channels",
        path="/channels",
        table_name="channels",
        params=CHANNEL_LIST_PARAMS,
        # A channel is listed only while it is active and its occupancy counts describe that
        # moment, so there is no timestamp to sync incrementally from. Each run replaces the
        # snapshot.
        primary_key=["channelId"],
    ),
    "ChannelMessages": AblyEndpointConfig(
        name="ChannelMessages",
        path="/channels/{channel_id}/messages",
        table_name="channel_messages",
        params={"direction": "forwards"},
        # `timestamp` is Unix ms, the same unit the `start`/`end` history params take.
        incremental_fields=[
            {
                "label": "Timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        default_incremental_field="timestamp",
        # ISO datetime derived from `timestamp` by `_add_message_time` in ably.py.
        partition_key="message_time",
        # Ably documents the message id as unique per publish, but a publisher can supply its own
        # id for idempotent publishing, so uniqueness is only guaranteed within a channel.
        primary_key=["channel_id", "id"],
        fanout=CHANNEL_FANOUT,
    ),
    "Presence": AblyEndpointConfig(
        name="Presence",
        path="/channels/{channel_id}/presence",
        table_name="presence",
        # Members currently present, which the API exposes with no time filter. Each run replaces
        # the snapshot.
        primary_key=["channel_id", "id"],
        fanout=CHANNEL_FANOUT,
    ),
}

ENDPOINTS = tuple(ABLY_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ABLY_ENDPOINTS.items()
}
