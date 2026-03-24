use axum::http::HeaderValue;

// Standard response header values
pub const ACCEPT_JSON: HeaderValue = HeaderValue::from_static("application/json");
pub const ACCEPT_ENCODING_ALL: HeaderValue = HeaderValue::from_static("gzip, deflate, br, zstd");
pub const DEFAULT_RETRY_AFTER_SECS: HeaderValue = HeaderValue::from_static("60");

// WWW-Authenticate challenge values
pub const WWW_AUTHENTICATE_MISSING: HeaderValue =
    HeaderValue::from_static(r#"Bearer realm="posthog", error="missing_token""#);
pub const WWW_AUTHENTICATE_INVALID: HeaderValue =
    HeaderValue::from_static(r#"Bearer realm="posthog", error="invalid_token""#);

// Custom header names
pub const POSTHOG_REQUEST_ID: &str = "PostHog-Request-Id";
pub const POSTHOG_API_TOKEN: &str = "PostHog-Api-Token";
pub const POSTHOG_SDK_INFO: &str = "PostHog-Sdk-Info";
pub const POSTHOG_ATTEMPT: &str = "PostHog-Attempt";
pub const POSTHOG_CLIENT_TIMESTAMP: &str = "PostHog-Client-Timestamp";

// Valid content encodings
pub const SUPPORTED_ENCODINGS: &[&str] = &["gzip", "deflate", "br", "zstd"];
