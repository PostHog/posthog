use axum::http::HeaderValue;

// ---------------------------------------------------------------------------
// HTTP response header values
// ---------------------------------------------------------------------------

/// JSON Accept header value for analytics responses.
pub const ACCEPT_JSON: HeaderValue = HeaderValue::from_static("application/json");

/// Accepted compression encodings advertised in Accept-Encoding response header.
pub const ACCEPT_ENCODING_ALL: HeaderValue = HeaderValue::from_static("gzip, deflate, br, zstd");

/// Default Retry-After value (seconds) sent on rate-limited or server-error responses.
pub const DEFAULT_RETRY_AFTER_SECS: HeaderValue = HeaderValue::from_static("60");

// ---------------------------------------------------------------------------
// Supported content encodings
// ---------------------------------------------------------------------------

/// Allowlist of content encodings the capture endpoint will decompress.
pub const SUPPORTED_ENCODINGS: &[&str] = &["gzip", "deflate", "br", "zstd"];

// ---------------------------------------------------------------------------
// Route paths
// ---------------------------------------------------------------------------

/// Primary route path for the v1 analytics events endpoint.
pub const CAPTURE_V1_PATH: &str = "/i/v1/general/analytics/events";

/// Trailing-slash variant registered so both URL forms resolve to the same handler.
pub(super) const CAPTURE_V1_PATH_TRAILING: &str = "/i/v1/general/analytics/events/";

// ---------------------------------------------------------------------------
// Metrics keys
// ---------------------------------------------------------------------------

/// Counter tracking parsed events, labeled valid vs malformed.
pub(super) const CAPTURE_V1_PARSED_EVENTS: &str = "capture_v1_parsed_events";

/// Counter for events rerouted to the historical ingestion destination.
pub(super) const CAPTURE_V1_EVENTS_REROUTED_HISTORICAL: &str =
    "capture_v1_events_rerouted_historical";

/// Counter for events dropped (e.g. due to event restrictions).
pub(super) const CAPTURE_V1_EVENTS_DROPPED: &str = "capture_v1_events_dropped";

/// Counter for events marked as quota-limited, labeled by resource bucket.
pub(crate) const CAPTURE_V1_EVENTS_QUOTA_LIMITED: &str = "capture_v1_events_quota_limited";

/// Counter/gauge key for the per-token global rate limiter.
pub(crate) const CAPTURE_V1_RATE_LIMITER: &str = "capture_v1_rate_limiter";

// ---------------------------------------------------------------------------
// Validation limits
// ---------------------------------------------------------------------------

/// Maximum allowed length for an event name; longer names are rejected.
pub(super) const CAPTURE_V1_MAX_EVENT_NAME_LENGTH: usize = 200;

/// Maximum allowed length for a distinct_id value; longer IDs are rejected.
pub(super) const CAPTURE_V1_DISTINCT_ID_MAX_SIZE: usize = 200;

// ---------------------------------------------------------------------------
// Timestamp normalization
// ---------------------------------------------------------------------------

/// Events whose skew-adjusted timestamp is more than 23 hours in the future
/// (in milliseconds) are clamped to server `now`.
pub(super) const FUTURE_EVENT_HOURS_CUTOFF_MS: i64 = 23 * 3600 * 1000;
