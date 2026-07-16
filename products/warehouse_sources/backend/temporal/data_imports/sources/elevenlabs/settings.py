from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ElevenLabsEndpointConfig:
    name: str
    # Path appended to ELEVENLABS_BASE_URL, including the API version (v1/v2 differ per endpoint).
    path: str
    # Top-level array key in the JSON response body (differs per endpoint: history/conversations/...).
    items_key: str
    # Query param used to request the next page, and the response field that carries the next cursor.
    # ElevenLabs uses three different cursor styles across endpoint families.
    cursor_param: str
    cursor_response_key: str
    primary_keys: list[str]
    page_size: int
    partition_key: str
    # Stable, monotonic incremental column and the server-side filter param that bounds it. Both None
    # for full-refresh endpoints (agents/voices expose no updated-since filter).
    incremental_field: Optional[str] = None
    incremental_param: Optional[str] = None
    # "asc" checkpoints the watermark after every batch; "desc" defers it to successful job end. Must
    # match the order rows actually arrive in for the endpoint.
    sort_mode: str = "asc"
    # Conversations are mutable (status/summary/sentiment fill in after the call), so they must merge
    # rather than append; immutable history items may append.
    supports_append: bool = False
    should_sync_default: bool = True
    # Constant query params merged into every request (sort direction, summary mode, ...).
    extra_params: dict[str, str] = field(default_factory=dict)


def _int_incremental_field(name: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.Integer,
            "field": name,
            "field_type": IncrementalFieldType.Integer,
        }
    ]


ELEVENLABS_ENDPOINTS: dict[str, ElevenLabsEndpointConfig] = {
    # Text-to-speech / speech-to-speech generation history. Immutable per-generation records, filtered
    # server-side by `date_after_unix` (inclusive) and returned ascending via `sort_direction=asc`.
    "history": ElevenLabsEndpointConfig(
        name="history",
        path="/v1/history",
        items_key="history",
        cursor_param="start_after_history_item_id",
        cursor_response_key="last_history_item_id",
        primary_keys=["history_item_id"],
        page_size=1000,
        partition_key="date_unix",
        incremental_field="date_unix",
        incremental_param="date_after_unix",
        sort_mode="asc",
        supports_append=True,
        extra_params={"sort_direction": "asc"},
    ),
    # Conversational AI calls. Mutable (status transitions, transcript summary and sentiment land after
    # the call completes) so they merge, never append. Cursor pagination exposes no sort param; the
    # default is newest-first, so we report "desc" and let the server-side `call_start_after_unix`
    # filter bound the set on incremental runs. `summary_mode=include` pulls the summary/sentiment.
    "conversations": ElevenLabsEndpointConfig(
        name="conversations",
        path="/v1/convai/conversations",
        items_key="conversations",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["conversation_id"],
        page_size=100,
        partition_key="start_time_unix_secs",
        incremental_field="start_time_unix_secs",
        incremental_param="call_start_after_unix",
        sort_mode="desc",
        supports_append=False,
        extra_params={"summary_mode": "include"},
    ),
    # Conversational AI agent configs. Small, mutable table with no updated-since filter, so full
    # refresh only. Ordered ascending by creation for stable pagination.
    "agents": ElevenLabsEndpointConfig(
        name="agents",
        path="/v1/convai/agents",
        items_key="agents",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["agent_id"],
        page_size=100,
        partition_key="created_at_unix_secs",
        sort_mode="asc",
        extra_params={"sort_by": "created_at", "sort_direction": "asc"},
    ),
    # Voice library. Small, mutable table with no updated-since filter, so full refresh only. v2 uses a
    # `next_page_token` cursor; `created_at_unix` may be null for older voices (bucketed as epoch 0).
    "voices": ElevenLabsEndpointConfig(
        name="voices",
        path="/v2/voices",
        items_key="voices",
        cursor_param="next_page_token",
        cursor_response_key="next_page_token",
        primary_keys=["voice_id"],
        page_size=100,
        partition_key="created_at_unix",
        sort_mode="asc",
        extra_params={"sort": "created_at_unix", "sort_direction": "asc"},
    ),
}

ENDPOINTS = tuple(ELEVENLABS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: (_int_incremental_field(config.incremental_field) if config.incremental_field else [])
    for name, config in ELEVENLABS_ENDPOINTS.items()
}
