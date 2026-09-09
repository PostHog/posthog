"""Canonical, documentation-sourced descriptions for Ably endpoints and columns.

Sourced from the official Ably REST API reference (https://ably.com/docs/api/rest-api) and the
Ably platform OpenAPI definition. Keyed by the resource names in `settings.py`
`ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Ably table. Columns absent
here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Stats": {
        "description": "Aggregated usage statistics for an Ably app over a fixed time interval — "
        "message/connection/channel volumes and API request counts, at the selected granularity.",
        "docs_url": "https://ably.com/docs/metadata-stats/stats",
        "columns": {
            "intervalId": "Identifier of the time interval, formatted according to `unit` "
            "(e.g. `2024-01-15:14` for an hourly bucket).",
            "unit": "Granularity of the interval: minute, hour, day, or month.",
            "interval_start": "UTC start of the interval, derived from `intervalId` and `unit`.",
            "schema": "URI of the JSON schema describing this stats record's shape.",
            "appId": "Identifier of the Ably app the stats belong to.",
            "inProgress": "Interval start time if these stats are for the current, still-accumulating interval.",
            "all": "Aggregate message statistics (count and data size) across all channels and protocols.",
            "inbound": "Breakdown of messages published into the app, by protocol (realtime/rest/webhook) and message type.",
            "outbound": "Breakdown of messages delivered from the app, by protocol and message type.",
            "persisted": "Count and size of messages persisted for the history API.",
            "connections": "Peak, minimum, mean, opened, and refused connection counts for the interval.",
            "channels": "Peak, minimum, mean, and opened channel counts for the interval.",
            "apiRequests": "Count of REST API requests made against the app, broken down as succeeded/failed/refused.",
            "tokenRequests": "Count of token requests made against the app, broken down as succeeded/failed/refused.",
            "pushNotifications": "Count of push notifications sent, broken down by outcome (succeeded/failed/invalid).",
        },
    },
    "Channels": {
        "description": "Metadata for every channel currently active in the Ably app, including "
        "the occupancy counts of connections attached to it.",
        "docs_url": "https://ably.com/docs/metadata-stats/metadata/rest",
        "columns": {
            "channelId": "Name of the channel, including its namespace qualifier if it has one.",
            "region": "Region the reported activity was observed in, when the record is region-scoped.",
            "isGlobalMaster": "Whether this region coordinates the channel globally.",
            "status": "Channel status: whether the channel is active, and its occupancy breakdown.",
        },
    },
    "ChannelMessages": {
        "description": "Messages published to a channel and retained by Ably's history feature. "
        "Ably keeps messages for two minutes unless persistence is enabled for the channel.",
        "docs_url": "https://ably.com/docs/storage-history/history",
        "columns": {
            "id": "Unique identifier for the message. A publisher can supply its own for idempotent publishing.",
            "channel_id": "Name of the channel the message was published to.",
            "name": "Event name the message was published under, if the publisher set one.",
            "data": "Message payload, encoded as described by `encoding`.",
            "encoding": "Transformations still to apply to `data`. Usually empty.",
            "clientId": "Client ID of the publisher, for identified clients.",
            "connectionId": "Connection ID of the publisher.",
            "timestamp": "Time Ably received the message, as milliseconds since the epoch.",
            "message_time": "UTC time Ably received the message, derived from `timestamp`.",
            "extras": "Extra fields carried with the message, such as push notification payloads.",
        },
    },
    "Presence": {
        "description": "Members currently present on each channel, one row per member.",
        "docs_url": "https://ably.com/docs/presence-occupancy/presence",
        "columns": {
            "id": "Unique identifier Ably assigned to this presence update.",
            "channel_id": "Name of the channel the member is present on.",
            "action": "Presence event this record represents: ABSENT, PRESENT, ENTER, LEAVE, or UPDATE.",
            "data": "Presence payload the member entered with, if any.",
            "clientId": "Client ID of the member.",
            "connectionId": "Connection ID the member is present through.",
            "timestamp": "Time Ably received the presence update, as milliseconds since the epoch.",
            "encoding": "Transformations still to apply to `data`. Usually empty.",
            "extras": "Extra fields carried with the presence update.",
        },
    },
}
