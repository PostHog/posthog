// ---------------------------------------------------------------------------
// Custom PostHog request header names
// ---------------------------------------------------------------------------
// Defined at the v1 level (not in analytics/) so that REQUIRED_HEADERS
// can reference them without a cross-submodule dependency.

/// Header carrying SDK name/version metadata.
pub const POSTHOG_SDK_INFO: &str = "PostHog-Sdk-Info";

/// Header indicating the SDK retry attempt number.
pub const POSTHOG_ATTEMPT: &str = "PostHog-Attempt";

/// Header carrying the SDK-generated unique request ID for deduplication.
pub const POSTHOG_REQUEST_ID: &str = "PostHog-Request-Id";

/// Header carrying the SDK-side timestamp of the request.
pub const POSTHOG_REQUEST_TIMESTAMP: &str = "PostHog-Request-Timestamp";

// ---------------------------------------------------------------------------
// Required request headers
// ---------------------------------------------------------------------------

/// Headers that must be present on every v1 analytics request.
/// Missing any of these triggers an Error::MissingRequiredHeaders response.
// Standard header names are inlined as &str because HeaderName::as_str() isn't const.
// They correspond to header::AUTHORIZATION, header::CONTENT_TYPE, header::USER_AGENT.
pub(super) const REQUIRED_HEADERS: &[&str] = &[
    "authorization",
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

/// Counter name for body-read timeouts during payload extraction.
pub(super) const CAPTURE_V1_BODY_READ_TIMEOUT: &str = "capture_v1_body_read_timeout_total";

// ---------------------------------------------------------------------------
// Fallback values
// ---------------------------------------------------------------------------

/// Histogram tracking end-to-end response time for v1 analytics requests.
pub(crate) const CAPTURE_V1_RESPONSE_TIME: &str = "capture_v1_response_time_seconds";

/// Fallback path label used in error metrics when no request context is available.
pub(super) const CAPTURE_V1_UNKNOWN_PATH: &str = "unknown";
