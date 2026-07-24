from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# First-sync window for the incremental video-views endpoint. Raw per-view rows have much tighter
# retention than aggregates and the list endpoint isn't a bulk export, so we start modest; subsequent
# syncs track the `view_end` watermark forward from here.
VIDEO_VIEWS_INITIAL_LOOKBACK = timedelta(days=30)
# Window for the full-refresh aggregate endpoints (errors, metric comparison). Mux Data retains
# engagement/QoE metrics for ~13 months, so this pulls essentially everything Mux keeps; Mux clamps
# the window to what's actually retained rather than erroring. The responses are small and replaced
# each sync, so a wide window is cheap.
AGGREGATE_LOOKBACK = timedelta(days=395)


@dataclass
class MuxEndpointConfig:
    name: str
    path: str
    # `created_at` is a stable Unix timestamp on most Mux Video objects, so it's a safe datetime
    # partition key. Endpoints whose objects have no `created_at` (uploads, all Mux Data endpoints)
    # leave this None and aren't partitioned. Mux Data timestamps are ISO 8601 strings, which the
    # datetime partitioner (expects Unix ints) can't parse, so Data endpoints stay unpartitioned.
    partition_key: Optional[str] = "created_at"
    # Mux caps list `limit` at 100 on most endpoints; transcription vocabularies cap it at 10.
    page_size: int = 100
    # Cursor pagination (`next_cursor`) is only available on List Assets today; every other
    # paginated list endpoint is offset-based (`page` + `limit`).
    use_cursor: bool = False
    # False for Mux Data endpoints that return the whole result set in one response (errors,
    # metric comparison) — those use a single-page paginator instead of walking pages.
    paginated: bool = True
    should_sync_default: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Credential-bearing fields Mux returns in list responses but that must never reach the warehouse:
    # importing them would let anyone who can query the table broadcast or upload media into the
    # connected Mux environment (an analytics-read → Mux-write escalation). Stripped before batching.
    sensitive_fields: tuple[str, ...] = ()
    # Mux Data endpoints scope results to a `timeframe[]` window (defaults to the last 24h if absent).
    # When True the source passes an explicit window so a sync captures a useful span, not just a day.
    use_timeframe: bool = False
    # Only video views expose a server-side timestamp filter (`view_end` via `timeframe[]`), so it's
    # the one Data endpoint that can sync incrementally; errors and metric aggregates are full refresh.
    supports_incremental: bool = False
    incremental_field: Optional[str] = None
    # How far back the `timeframe[]` window reaches when there's no watermark (first sync or a
    # full-refresh endpoint). Only meaningful when `use_timeframe` is set.
    lookback: timedelta = AGGREGATE_LOOKBACK


MUX_ENDPOINTS: dict[str, MuxEndpointConfig] = {
    # --- Mux Video: content-level metadata (assets, live streams, uploads, ...) ---
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
    # --- Mux Data: viewer engagement and quality-of-experience analytics ---
    "video_views": MuxEndpointConfig(
        name="video_views",
        path="/data/v1/video-views",
        # Timestamps are ISO 8601 strings (`view_start` / `view_end`), not the Unix `created_at`
        # the datetime partitioner understands, so this table is left unpartitioned.
        partition_key=None,
        use_timeframe=True,
        supports_incremental=True,
        incremental_field="view_end",
        lookback=VIDEO_VIEWS_INITIAL_LOOKBACK,
    ),
    "errors": MuxEndpointConfig(
        name="errors",
        path="/data/v1/errors",
        partition_key=None,
        # Aggregated over the window in a single response — no pagination.
        paginated=False,
        use_timeframe=True,
    ),
    "metrics_comparison": MuxEndpointConfig(
        name="metrics_comparison",
        path="/data/v1/metrics/comparison",
        partition_key=None,
        # One aggregate row per metric, returned in a single response.
        paginated=False,
        primary_keys=["metric"],
        use_timeframe=True,
    ),
}

ENDPOINTS = tuple(MUX_ENDPOINTS.keys())

# Only video views support a server-side timestamp filter (`view_end` within `timeframe[]`), so it's
# the sole endpoint with genuine incremental sync. Its field type is DateTime because Mux Data returns
# ISO 8601 strings (e.g. "2023-01-01T00:00:00Z"), unlike the Unix-timestamp Mux Video endpoints. Every
# other endpoint has no server-side filter and is full refresh only — no advertised incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "video_views": [
        {
            "label": "view_end",
            "type": IncrementalFieldType.DateTime,
            "field": "view_end",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
