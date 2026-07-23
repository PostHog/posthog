"""Canonical, documentation-sourced descriptions for Ably endpoints and columns.

Sourced from the official Ably REST API reference (https://ably.com/docs/api/rest-api#stats and
https://ably.com/docs/metadata-stats/stats). Keyed by the resource names in `settings.py`
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
}
