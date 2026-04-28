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

/// Primary route path for the v1 events endpoint.
pub const CAPTURE_V1_PATH: &str = "/i/v1/general/events";

/// Trailing-slash variant registered so both URL forms resolve to the same handler.
pub(super) const CAPTURE_V1_PATH_TRAILING: &str = "/i/v1/general/events/";

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

/// Detail tag for events flagged by the per-token:distinct_id rate limiter.
pub(super) const DETAIL_RATE_LIMITED_TOKEN_DISTINCT_ID: &str = "rate_limited_token_distinct_id";

// ---------------------------------------------------------------------------
// Payload size limits
// ---------------------------------------------------------------------------

/// Maximum compressed (wire) body size the v1 endpoint will accept.
/// The decompressed limit is separately enforced via `state.event_payload_size_limit`.
pub(super) const CAPTURE_V1_MAX_COMPRESSED_BODY_BYTES: usize = 10 * 1024 * 1024; // 10MB

// ---------------------------------------------------------------------------
// Validation limits
// ---------------------------------------------------------------------------

/// Maximum allowed length for an event name; longer names are rejected.
pub(super) const CAPTURE_V1_MAX_EVENT_NAME_LENGTH: usize = 200;

/// Maximum allowed length for a distinct_id value; longer IDs are rejected.
pub(super) const CAPTURE_V1_DISTINCT_ID_MAX_SIZE: usize = 200;

// ---------------------------------------------------------------------------
// Illegal distinct_id values
// ---------------------------------------------------------------------------

/// Known-bad distinct_id values that indicate a bug or misconfiguration in the
/// sending SDK. Ported from the Node.js ingestion pipeline
/// (nodejs/src/worker/ingestion/persons/person-merge-service.ts) with
/// additions from the new #ingestion-reports feed.
///
/// All comparisons are case-insensitive after trimming whitespace, which is a
/// deliberate simplification over Node.js (which splits into case-sensitive and
/// case-insensitive sets).
pub(super) const ILLEGAL_DISTINCT_IDS: &[&str] = &[
    "0",
    "00000000-0000-0000-0000-000000000000",
    "[object object]",
    "anonymous",
    "anonymous-user",
    "backend",
    "distinct_id",
    "distinctid",
    "email",
    "false",
    "guest",
    "id",
    "nan",
    "none",
    "not_authenticated",
    "null",
    "system",
    "true",
    "undefined",
    "user",
];

// ---------------------------------------------------------------------------
// Timestamp normalization
// ---------------------------------------------------------------------------

/// Events whose skew-adjusted timestamp is more than 23 hours in the future
/// (in milliseconds) are clamped to server `now`.
pub(super) const FUTURE_EVENT_HOURS_CUTOFF_MS: i64 = 23 * 3600 * 1000;
