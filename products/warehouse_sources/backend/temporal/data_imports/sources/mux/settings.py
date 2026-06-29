from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class MuxEndpointConfig:
    name: str
    path: str
    # `created_at` is a stable Unix timestamp on most Mux objects, so it's a safe datetime partition key.
    # Endpoints whose objects have no `created_at` (e.g. uploads) leave this None and aren't partitioned.
    partition_key: Optional[str] = "created_at"
    # Mux caps list `limit` at 100 on most endpoints; transcription vocabularies cap it at 10.
    page_size: int = 100
    # Cursor pagination (`next_cursor`) is only available on List Assets today; every other
    # list endpoint is offset-based (`page` + `limit`).
    use_cursor: bool = False
    should_sync_default: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Credential-bearing fields Mux returns in list responses but that must never reach the warehouse:
    # importing them would let anyone who can query the table broadcast or upload media into the
    # connected Mux environment (an analytics-read → Mux-write escalation). Stripped before batching.
    sensitive_fields: tuple[str, ...] = ()


MUX_ENDPOINTS: dict[str, MuxEndpointConfig] = {
    "assets": MuxEndpointConfig(
        name="assets",
        path="/video/v1/assets",
        use_cursor=True,
    ),
    "live_streams": MuxEndpointConfig(
        name="live_streams",
        path="/video/v1/live-streams",
        # `stream_key` is the secret RTMP ingest key for broadcasting to the stream.
        sensitive_fields=("stream_key",),
    ),
    "uploads": MuxEndpointConfig(
        name="uploads",
        path="/video/v1/uploads",
        # The Direct Upload object has no `created_at`, so it can't be datetime-partitioned.
        partition_key=None,
        # `url` is the authenticated PUT URL for pushing media into the upload.
        sensitive_fields=("url",),
    ),
    "playback_restrictions": MuxEndpointConfig(
        name="playback_restrictions",
        path="/video/v1/playback-restrictions",
    ),
    "transcription_vocabularies": MuxEndpointConfig(
        name="transcription_vocabularies",
        path="/video/v1/transcription-vocabularies",
        page_size=10,
    ),
    "signing_keys": MuxEndpointConfig(
        name="signing_keys",
        path="/system/v1/signing-keys",
    ),
}

ENDPOINTS = tuple(MUX_ENDPOINTS.keys())

# Mux's list endpoints expose no server-side created/updated timestamp filter, so every stream is
# full refresh only — there are no advertised incremental fields. See the skill's incremental-sync
# guidance: a client-side `created_at` cursor would still page the whole collection, so it isn't
# genuine incremental sync.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
