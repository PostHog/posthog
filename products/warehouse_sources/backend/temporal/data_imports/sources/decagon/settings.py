from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


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
    # Whether the append sync type is offered alongside incremental. Streams whose
    # rows mutate in place must leave this False: appends would accumulate one copy
    # per mutation, and only a merge keeps the table at one row per primary key.
    supports_append: bool = False


# Decagon's syncable surface is a single stream: /conversation/export returns
# conversations with their messages, CSAT ratings, tags, and metadata, up to 100
# per page. Pagination is a `cursor` request param fed from a next-page response
# field whose name varies across Decagon's own docs (see NEXT_CURSOR_KEYS in
# decagon.py); it is null once the stream is exhausted. The export also accepts
# min_timestamp/max_timestamp filters (epoch seconds), with `timestamp_filter`
# selecting the field they bound: created_at (the default), updated_at, or
# last_message_time. Rows always carry `updated_at` (ISO 8601), so the stream
# syncs incrementally by filtering on updated_at and merging on conversation_id.
# A conversation re-enters the export whenever it receives new messages, which is
# why the vendor recommends upserting on conversation_id rather than appending.
DECAGON_ENDPOINTS: dict[str, DecagonEndpointConfig] = {
    "conversations": DecagonEndpointConfig(
        name="conversations",
        path="/conversation/export",
        data_key="conversations",
        primary_keys=["conversation_id"],
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_key="created_at",
        # A conversation row mutates in place whenever new messages arrive.
        supports_append=False,
    ),
}

ENDPOINTS = tuple(DECAGON_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DECAGON_ENDPOINTS.items()
}
