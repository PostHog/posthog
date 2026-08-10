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
# conversations with their messages, CSAT ratings, tags, and metadata, up to 100
# per page. Pagination is a `cursor` request param fed from a next-page response
# field whose name varies across Decagon's own docs (see NEXT_CURSOR_KEYS in
# decagon.py); it is null once the stream is exhausted. The export also accepts
# optional min_timestamp/max_timestamp filters on a conversation's last-updated
# time, but rows expose no last-updated column our incremental machinery could
# store as a watermark (only created_at, and a conversation re-enters the stream
# whenever it receives new messages), so the stream is full refresh only.
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
