from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ElevenLabsEndpointConfig:
    name: str
    # List endpoint path, relative to the API base URL.
    path: str
    # Key the list of objects is nested under in the response body (e.g. {"history": [...]}).
    # None means the response body itself is the list (models).
    data_key: Optional[str]
    primary_key: str
    # ElevenLabs mixes three cursor styles across endpoint families, so both sides of the
    # cursor round-trip are declared per endpoint: the request query param we send the cursor
    # in, and the response body key the next cursor comes back under. None = no pagination.
    cursor_param: Optional[str] = None
    cursor_response_key: Optional[str] = None
    page_size: Optional[int] = None
    # Server-side incremental filter query param, taking a unix-seconds timestamp. None means
    # the endpoint has no server-side timestamp filter and syncs as full refresh only.
    incremental_param: Optional[str] = None
    # Static query params sent on every request (e.g. an explicit sort direction).
    extra_params: dict[str, str] = field(default_factory=dict)
    sort_mode: SortMode = "desc"
    # Field used to partition the warehouse table. Must be a stable creation timestamp,
    # never an updated_at-style field that rewrites partitions on every sync.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    schema_description: Optional[str] = None


# ElevenLabs timestamps are UNIX epoch seconds, so candidate incremental fields are stored as
# integers even though the UI presents them as datetimes. Incremental sync is only enabled
# where the API documents a server-side timestamp filter that lines up with a stable field on
# the returned rows (history -> date_after_unix filters on date_unix, conversations ->
# call_start_after_unix filters on start_time_unix_secs). Everything else is full refresh.
#
# The timestamp filters are taken from the published OpenAPI spec (date_after_unix is
# documented inclusive); they could not be smoke-tested against the live API without
# credentials, so the descending endpoints also carry a client-side watermark stop in the
# transport as a belt-and-braces guard (see elevenlabs.py).
ELEVENLABS_ENDPOINTS: dict[str, ElevenLabsEndpointConfig] = {
    "history": ElevenLabsEndpointConfig(
        name="history",
        path="/v1/history",
        data_key="history",
        primary_key="history_item_id",
        cursor_param="start_after_history_item_id",
        cursor_response_key="last_history_item_id",
        page_size=1000,
        incremental_param="date_after_unix",
        # Ascending creation order keeps already-fetched pages stable and lets the incremental
        # watermark advance monotonically as pages are yielded.
        extra_params={"sort_direction": "asc"},
        sort_mode="asc",
        partition_key="date_unix",
        incremental_fields=[
            {
                "label": "date_unix",
                "type": IncrementalFieldType.DateTime,
                "field": "date_unix",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        schema_description="Speech generation history items: the text, voice, model, and character cost of each generation.",
    ),
    "conversations": ElevenLabsEndpointConfig(
        name="conversations",
        path="/v1/convai/conversations",
        data_key="conversations",
        primary_key="conversation_id",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        page_size=100,
        incremental_param="call_start_after_unix",
        # The conversations list has no sort parameter and returns newest-first.
        sort_mode="desc",
        partition_key="start_time_unix_secs",
        incremental_fields=[
            {
                "label": "start_time_unix_secs",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time_unix_secs",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        schema_description="Conversational AI conversations: duration, status, call success, message counts, and summaries.",
    ),
    "agents": ElevenLabsEndpointConfig(
        name="agents",
        path="/v1/convai/agents",
        data_key="agents",
        primary_key="agent_id",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        page_size=100,
        # No server-side timestamp filter — full refresh only. Newest-first by default.
        sort_mode="desc",
        partition_key="created_at_unix_secs",
        schema_description="Conversational AI agents configured in the workspace.",
    ),
    "voices": ElevenLabsEndpointConfig(
        name="voices",
        path="/v2/voices",
        data_key="voices",
        primary_key="voice_id",
        cursor_param="next_page_token",
        cursor_response_key="next_page_token",
        page_size=100,
        # No server-side timestamp filter — full refresh only. created_at_unix is nullable on
        # older/premade voices, so the table is not partitioned on it.
        sort_mode="desc",
        schema_description="Voices available to the workspace, including cloned and professional voices.",
    ),
    "models": ElevenLabsEndpointConfig(
        name="models",
        path="/v1/models",
        data_key=None,
        primary_key="model_id",
        # Small static catalog returned as a bare list in a single response — no pagination.
        sort_mode="desc",
        schema_description="Speech models available on the account, with capabilities and cost factors.",
    ),
}

ENDPOINTS = tuple(ELEVENLABS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ELEVENLABS_ENDPOINTS.items() if config.incremental_fields
}
