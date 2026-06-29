// ---------------------------------------------------------------------------
// Custom PostHog request header names
// ---------------------------------------------------------------------------
// Defined at the v1 level (not in analytics/) so that REQUIRED_HEADERS
// can reference them without a cross-submodule dependency.

/// Header carrying SDK name/version metadata.
pub const POSTHOG_SDK_INFO: &str = "PostHog-Sdk-Info";

/// Max accepted `PostHog-Sdk-Info` length (real values are ~20 bytes). Longer
/// values skip `$lib` injection so an oversized header can't be amplified
/// into every event of a batch.
pub(super) const MAX_SDK_INFO_LEN: usize = 200;

/// Header indicating the SDK retry attempt number.
pub const POSTHOG_ATTEMPT: &str = "PostHog-Attempt";

/// Header carrying the SDK-generated unique request ID for deduplication.
pub const POSTHOG_REQUEST_ID: &str = "PostHog-Request-Id";

/// Header carrying the SDK-side timestamp of the request.
pub const POSTHOG_REQUEST_TIMESTAMP: &str = "PostHog-Request-Timestamp";

/// AI-gateway provenance: lowercase-hex HMAC-SHA256 over the canonical tuple
/// (token, distinct_id, request_id, signed_at). See `gateway_provenance::canonical`.
pub const POSTHOG_AI_GATEWAY_SIGNATURE: &str = "PostHog-Ai-Gateway-Signature";

/// AI-gateway provenance: RFC3339 timestamp the gateway signed at.
pub const POSTHOG_AI_GATEWAY_SIGNED_AT: &str = "PostHog-Ai-Gateway-Signed-At";

/// AI-gateway provenance: per-call request id; billing dedups exemptions by it.
pub const POSTHOG_AI_GATEWAY_REQUEST_ID: &str = "PostHog-Ai-Gateway-Request-Id";

// ---------------------------------------------------------------------------
// Supported content encodings
// ---------------------------------------------------------------------------

/// Allowlist of content encodings the capture endpoint will decompress.
/// Lives at the v1 level (not in analytics/) so request-context decoding is
/// CaptureMode-agnostic.
pub const SUPPORTED_ENCODINGS: &[&str] = &["gzip", "deflate", "br", "zstd"];

// ---------------------------------------------------------------------------
// Required request headers
// ---------------------------------------------------------------------------

/// Headers that must be present on every v1 analytics request.
/// Missing any of these triggers an Error::MissingRequiredHeaders response.
// Standard header names are inlined as &str because HeaderName::as_str() isn't const.
// They correspond to header::AUTHORIZATION, header::CONTENT_TYPE, header::USER_AGENT.
pub(super) const REQUIRED_HEADERS: &[&str] = &[
    POSTHOG_SDK_INFO,
    POSTHOG_ATTEMPT,
    POSTHOG_REQUEST_ID,
    POSTHOG_REQUEST_TIMESTAMP,
    "content-type",
    "user-agent",
];

// ---------------------------------------------------------------------------
// Metrics keys
// ---------------------------------------------------------------------------

/// Counter name for v1 analytics errors (labels: error, level, path, status_code).
pub(super) const CAPTURE_V1_ERROR_METRIC: &str = "capture_v1_analytics_error";

/// Counter for non-fatal conditions on otherwise-successful v1 requests
/// (labels: reason, path). Shared key to avoid single-use metrics in Grafana.
pub(super) const CAPTURE_V1_WARNING_METRIC: &str = "capture_v1_analytics_warning";

/// Counter name for body-read timeouts during payload extraction.
pub(super) const CAPTURE_V1_BODY_READ_TIMEOUT: &str = "capture_v1_body_read_timeout_total";

/// Counter for streaming decompression failures (label: encoding).
pub(super) const CAPTURE_V1_DECOMPRESSION_ERRORS: &str = "capture_v1_decompression_errors_total";

/// Histogram of events per request batch. The `_batch_size` suffix picks up
/// the shared BATCH_SIZES buckets configured in prometheus.rs.
pub(super) const CAPTURE_V1_EVENT_BATCH_SIZE: &str = "capture_v1_event_batch_size";

/// Histogram of request payload sizes in bytes (label: stage = compressed |
/// decompressed). Buckets configured in prometheus.rs (PAYLOAD_SIZES).
pub(super) const CAPTURE_V1_PAYLOAD_SIZE: &str = "capture_v1_payload_size_bytes";

/// Histogram of absolute client clock skew in seconds, from the
/// PostHog-Request-Timestamp header vs. server receive time. Buckets
/// configured in prometheus.rs (CLOCK_SKEW_SECONDS).
pub(super) const CAPTURE_V1_CLOCK_SKEW_SECONDS: &str = "capture_v1_clock_skew_seconds";

/// Histogram of batch serialize wall-time (label: batch_size bucket). Sink- and
/// product-agnostic by design — faceting comes from the per-mode service
/// deployment (capture-analytics / capture-replay / capture-ai).
pub(super) const CAPTURE_V1_SERIALIZE_DURATION_SECONDS: &str =
    "capture_v1_serialize_duration_seconds";

/// Counter of events that failed to serialize (non-panic, fatal/non-retriable).
pub(super) const CAPTURE_V1_SERIALIZE_FAILED_TOTAL: &str = "capture_v1_serialize_failed_total";

/// Counter of events whose serialization panicked. The panic is isolated per
/// event (caught), so the rest of the batch still serializes and publishes.
pub(super) const CAPTURE_V1_SERIALIZE_PANIC_TOTAL: &str = "capture_v1_serialize_panic_total";

// ---------------------------------------------------------------------------
// Fallback values
// ---------------------------------------------------------------------------

/// Histogram tracking end-to-end response time for v1 analytics requests.
pub(crate) const CAPTURE_V1_RESPONSE_TIME: &str = "capture_v1_response_time_seconds";

/// Fallback path label used in error metrics when no request context is available.
pub(super) const CAPTURE_V1_UNKNOWN_PATH: &str = "unknown";
