from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# First-sync window for the incremental video-views endpoint. Raw per-view rows have much tighter
# retention than aggregates and the list endpoint isn't a bulk export, so we start modest; subsequent
# syncs track the `view_end` watermark forward from here.
VIDEO_VIEWS_INITIAL_LOOKBACK = timedelta(days=30)
# Window for the full-refresh aggregate endpoints (errors, metric comparison). Mux Data's standard
# retention for these metrics is 100 days; 13-month retention is a paid add-on not every account has.
# A window past the account's retention is rejected with `400 invalid_timeframe` rather than clamped,
# so stay within the 100-day floor every plan supports. The responses are small and replaced each
# sync, so a wide window is cheap.
AGGREGATE_LOOKBACK = timedelta(days=90)

# Every metric the Mux Data breakdown and timeseries endpoints accept (`METRIC_ID` in the API reference).
DATA_METRICS: tuple[str, ...] = (
    "aggregate_startup_time",
    "downscale_percentage",
    "exits_before_video_start",
    "live_stream_latency",
    "max_downscale_percentage",
    "max_request_latency",
    "max_upscale_percentage",
    "page_load_time",
    "playback_failure_percentage",
    "playback_success_score",
    "player_startup_time",
    "playing_time",
    "rebuffer_count",
    "rebuffer_duration",
    "rebuffer_frequency",
    "rebuffer_percentage",
    "request_latency",
    "request_throughput",
    "rebuffer_score",
    "requests_for_first_preroll",
    "seek_latency",
    "startup_time_score",
    "unique_viewers",
    "upscale_percentage",
    "video_quality_score",
    "video_startup_preroll_load_time",
    "video_startup_preroll_request_time",
    "video_startup_time",
    "viewer_experience_score",
    "views",
    "weighted_average_bitrate",
    "video_startup_failure_percentage",
    "ad_attempt_count",
    "ad_break_count",
    "ad_break_error_count",
    "ad_break_error_percentage",
    "ad_error_count",
    "ad_error_percentage",
    "ad_exit_before_start_count",
    "ad_exit_before_start_percentage",
    "ad_impression_count",
    "ad_startup_error_count",
    "ad_startup_error_percentage",
    "playback_business_exception_percentage",
    "video_startup_business_exception_percentage",
    "view_content_startup_time",
    "ad_preroll_startup_time",
    "view_dropped_percentage",
    "rendition_change_count",
    "rendition_upshift_count",
    "rendition_downshift_count",
)
# Mux accepts ~90 breakdown dimensions and the table issues one request per metric per dimension, so
# it covers the dimensions QoE triage usually starts from rather than all of them.
BREAKDOWN_DIMENSIONS: tuple[str, ...] = (
    "country",
    "cdn",
    "browser",
    "operating_system",
    "player_name",
    "viewer_device_category",
)
# Identifier dimensions (view_session_id, viewer_user_id, ...) can have one value per view, so a full
# walk would re-read the whole view history. Cap each dimension at this many pages of values.
DIMENSION_VALUES_MAX_PAGES = 50


@dataclass(frozen=True)
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
    # Mux Data endpoints keyed by a metric or dimension in the path. The source issues one request
    # stream per metric (`metrics`), per metric and breakdown dimension (`metric_dimensions`), or per
    # dimension listed by `/data/v1/dimensions` (`dimensions`), and adds the key to each row.
    fan_out: Optional[Literal["metrics", "metric_dimensions", "dimensions"]] = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    max_pages: Optional[int] = None


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
    "metric_timeseries": MuxEndpointConfig(
        name="metric_timeseries",
        path="/data/v1/metrics/{metric}/timeseries",
        partition_key=None,
        # One response per metric holds every interval in the window.
        paginated=False,
        primary_keys=["metric", "interval_start"],
        use_timeframe=True,
        fan_out="metrics",
        # Without an explicit granularity Mux picks one from the window length and may change it.
        extra_params={"group_by": "day"},
    ),
    "metric_breakdowns": MuxEndpointConfig(
        name="metric_breakdowns",
        path="/data/v1/metrics/{metric}/breakdown?group_by={dimension}",
        partition_key=None,
        primary_keys=["metric", "dimension", "field"],
        use_timeframe=True,
        fan_out="metric_dimensions",
        # A stable order keeps page boundaries fixed while the walk runs.
        extra_params={"order_by": "field", "order_direction": "asc"},
        # Hundreds of requests per sync, so only on when the user picks it.
        should_sync_default=False,
    ),
    "dimensions": MuxEndpointConfig(
        name="dimensions",
        path="/data/v1/dimensions",
        partition_key=None,
        paginated=False,
        primary_keys=["name"],
    ),
    "dimension_values": MuxEndpointConfig(
        name="dimension_values",
        path="/data/v1/dimensions/{values_path}",
        partition_key=None,
        primary_keys=["dimension", "value"],
        use_timeframe=True,
        fan_out="dimensions",
        max_pages=DIMENSION_VALUES_MAX_PAGES,
        should_sync_default=False,
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
