from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class DecagonEndpointConfig:
    name: str
    path: str
    # Top-level key in the JSON response that holds the list of rows
    # (e.g. `{"conversations": [...]}` -> `"conversations"`).
    data_key: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for partitioning. Must never change for a row
    # (so `created_at`, never `updated_at`).
    partition_key: str


# Decagon's syncable surface is a single stream: /conversation/export returns
# conversations with their messages, CSAT ratings, tags, and metadata, paginated
# with a `cursor` request param and a `next_page_cursor` response field (null once
# exhausted, up to 100 conversations per page). There is no server-side timestamp
# filter, so the stream is full refresh only — the export cursor is an opaque
# stream position, not a durable watermark our incremental machinery can use.
DECAGON_ENDPOINTS: dict[str, DecagonEndpointConfig] = {
    "conversations": DecagonEndpointConfig(
        name="conversations",
        path="/conversation/export",
        data_key="conversations",
        primary_keys=["conversation_id"],
        incremental_fields=[],
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(DECAGON_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DECAGON_ENDPOINTS.items()
}
