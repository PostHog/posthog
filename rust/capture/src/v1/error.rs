use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use metrics::counter;
use serde::Serialize;
use thiserror::Error;
use tracing::Level;

use crate::v1::analytics::header::{
    ACCEPT_ENCODING_ALL, ACCEPT_JSON, DEFAULT_RETRY_AFTER_SECS, WWW_AUTHENTICATE_INVALID,
    WWW_AUTHENTICATE_MISSING,
};

const ERROR_METRIC_KEY: &str = "capture_v1_analytics_error";

#[derive(Debug, Clone, Serialize)]
pub struct ErrorResponse {
    pub error: String,
    pub error_description: String,
    pub error_uri: String,
}

impl ErrorResponse {
    fn new(error: &Error) -> Self {
        Self {
            error: error.tag().to_string(),
            error_description: error.description(),
            error_uri: error.error_uri().to_string(),
        }
    }
}

#[derive(Debug, Error)]
pub enum Error {
    // 400 - validation_error
    #[error("request is missing required headers: {0:?}")]
    MissingRequiredHeaders(Vec<String>),
    #[error("invalid header value: {0}")]
    InvalidHeaderValue(String),
    #[error("failed to decode request: {0}")]
    RequestDecodingError(String),
    #[error("failed to parse request: {0}")]
    RequestParsingError(String),
    #[error("request body is empty")]
    EmptyBody,
    #[error("request batch is empty")]
    EmptyBatch,
    #[error("invalid batch: {0}")]
    InvalidBatch(String),
    #[error("event submitted without an event name")]
    MissingEventName,
    #[error("event name exceeds maximum length")]
    EventNameTooLong,
    #[error("event submitted without a distinct_id")]
    MissingDistinctId,
    #[error("distinct_id exceeds maximum size")]
    DistinctIdTooLarge,
    #[error("event submitted without a uuid")]
    MissingEventUuid,
    #[error("duplicate event uuid: {0}")]
    DuplicateEventUuid(String),
    #[error("event submitted with invalid timestamp")]
    InvalidEventTimestamp,

    // 401 - authentication_error
    #[error("request is missing an API token")]
    MissingApiToken,
    #[error("API token is not valid: {0}")]
    InvalidApiToken(String),

    // 413 - payload_error
    #[error("payload too large: {0}")]
    PayloadTooLarge(String),

    // 415 - payload_error
    #[error("unsupported content type: {0}")]
    UnsupportedContentType(String),
    #[error("unsupported content encoding: {0}")]
    UnsupportedEncoding(String),

    // 408 - validation_error
    #[error("request timed out")]
    RequestTimeout,
    #[error("body read stalled after receiving {0} bytes")]
    BodyReadTimeout(usize),

    // 429 - rate_limit_error
    #[error("billing limit exceeded")]
    BillingLimitExceeded,
    #[error("rate limited: {0}")]
    RateLimited(String),

    // 500 - server_error
    #[error("internal server error: {0}")]
    InternalError(String),

    // 503 - server_error
    #[error("service unavailable: {0}")]
    ServiceUnavailable(String),

    // 504 - server_error
    #[error("gateway timeout")]
    GatewayTimeout,
}

impl Error {
    pub fn tag(&self) -> &'static str {
        match self {
            Self::MissingRequiredHeaders(_) => "missing_required_headers",
            Self::InvalidHeaderValue(_) => "invalid_header_value",
            Self::RequestDecodingError(_) => "request_decoding_error",
            Self::RequestParsingError(_) => "request_parsing_error",
            Self::EmptyBody => "empty_body",
            Self::EmptyBatch => "empty_batch",
            Self::InvalidBatch(_) => "invalid_batch",
            Self::MissingEventName => "missing_event_name",
            Self::EventNameTooLong => "event_name_too_long",
            Self::MissingDistinctId => "missing_distinct_id",
            Self::DistinctIdTooLarge => "distinct_id_too_large",
            Self::MissingEventUuid => "missing_event_uuid",
            Self::DuplicateEventUuid(_) => "duplicate_event_uuid",
            Self::InvalidEventTimestamp => "invalid_event_timestamp",
            Self::RequestTimeout => "request_timeout",
            Self::BodyReadTimeout(_) => "body_read_timeout",
            Self::MissingApiToken => "missing_api_token",
            Self::InvalidApiToken(_) => "invalid_api_token",
            Self::PayloadTooLarge(_) => "payload_too_large",
            Self::UnsupportedContentType(_) => "unsupported_content_type",
            Self::UnsupportedEncoding(_) => "unsupported_encoding",
            Self::BillingLimitExceeded => "billing_limit_exceeded",
            Self::RateLimited(_) => "rate_limited",
            Self::InternalError(_) => "internal_error",
            Self::ServiceUnavailable(_) => "service_unavailable",
            Self::GatewayTimeout => "gateway_timeout",
        }
    }

    pub fn description(&self) -> String {
        match self {
            Self::RequestDecodingError(_) => "Failed to decode request body.".to_string(),
            Self::RequestParsingError(_) => "Failed to parse request body.".to_string(),
            Self::InvalidApiToken(_) => {
                "The provided API token is not valid or has been revoked.".to_string()
            }
            Self::RateLimited(_) => "Rate limit exceeded.".to_string(),
            Self::InternalError(_) | Self::ServiceUnavailable(_) | Self::GatewayTimeout => self
                .status_code()
                .canonical_reason()
                .unwrap_or("server error")
                .to_string(),
            _ => self.to_string(),
        }
    }

    // TODO: turn into a per-error match arm with specific doc links
    pub fn error_uri(&self) -> &'static str {
        "https://posthog.com/docs/api"
    }

    pub fn log_level(&self) -> Level {
        match self {
            // 4xx client errors: warn
            Self::MissingRequiredHeaders(_)
            | Self::InvalidHeaderValue(_)
            | Self::RequestDecodingError(_)
            | Self::RequestParsingError(_)
            | Self::EmptyBody
            | Self::EmptyBatch
            | Self::InvalidBatch(_)
            | Self::MissingEventName
            | Self::EventNameTooLong
            | Self::MissingDistinctId
            | Self::DistinctIdTooLarge
            | Self::MissingEventUuid
            | Self::DuplicateEventUuid(_)
            | Self::InvalidEventTimestamp
            | Self::RequestTimeout
            | Self::MissingApiToken
            | Self::InvalidApiToken(_)
            | Self::PayloadTooLarge(_)
            | Self::UnsupportedContentType(_)
            | Self::UnsupportedEncoding(_)
            | Self::BillingLimitExceeded
            | Self::RateLimited(_) => Level::WARN,

            // body read timeout: error-level despite being 4xx
            Self::BodyReadTimeout(_) => Level::ERROR,

            // 5xx server errors: error
            Self::InternalError(_) | Self::ServiceUnavailable(_) | Self::GatewayTimeout => {
                Level::ERROR
            }
        }
    }

    fn level_tag(&self) -> &'static str {
        match self.log_level() {
            Level::WARN => "warn",
            _ => "error",
        }
    }

    pub(crate) fn stat_error(&self) {
        let tags = [("error", self.tag()), ("level", self.level_tag())];
        counter!(ERROR_METRIC_KEY, &tags).increment(1);
    }

    pub fn status_code(&self) -> StatusCode {
        match self {
            Self::MissingRequiredHeaders(_)
            | Self::InvalidHeaderValue(_)
            | Self::RequestDecodingError(_)
            | Self::RequestParsingError(_)
            | Self::EmptyBody
            | Self::EmptyBatch
            | Self::InvalidBatch(_)
            | Self::MissingEventName
            | Self::EventNameTooLong
            | Self::MissingDistinctId
            | Self::DistinctIdTooLarge
            | Self::MissingEventUuid
            | Self::DuplicateEventUuid(_)
            | Self::InvalidEventTimestamp => StatusCode::BAD_REQUEST,

            Self::RequestTimeout | Self::BodyReadTimeout(_) => StatusCode::REQUEST_TIMEOUT,

            Self::MissingApiToken | Self::InvalidApiToken(_) => StatusCode::UNAUTHORIZED,

            Self::PayloadTooLarge(_) => StatusCode::PAYLOAD_TOO_LARGE,

            Self::UnsupportedContentType(_) | Self::UnsupportedEncoding(_) => {
                StatusCode::UNSUPPORTED_MEDIA_TYPE
            }

            Self::BillingLimitExceeded | Self::RateLimited(_) => StatusCode::TOO_MANY_REQUESTS,

            Self::InternalError(_) => StatusCode::INTERNAL_SERVER_ERROR,

            Self::ServiceUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,

            Self::GatewayTimeout => StatusCode::GATEWAY_TIMEOUT,
        }
    }

    pub fn response_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(header::ACCEPT, ACCEPT_JSON);
        headers.insert(header::ACCEPT_ENCODING, ACCEPT_ENCODING_ALL);

        match self {
            Self::MissingApiToken => {
                headers.insert(header::WWW_AUTHENTICATE, WWW_AUTHENTICATE_MISSING);
            }
            Self::InvalidApiToken(_) => {
                headers.insert(header::WWW_AUTHENTICATE, WWW_AUTHENTICATE_INVALID);
            }
            Self::BillingLimitExceeded | Self::RateLimited(_) => {
                headers.insert(header::RETRY_AFTER, DEFAULT_RETRY_AFTER_SECS);
            }
            Self::InternalError(_) | Self::ServiceUnavailable(_) => {
                headers.insert(header::RETRY_AFTER, DEFAULT_RETRY_AFTER_SECS);
            }
            _ => {}
        }

        headers
    }
}

/// Logs at `warn!` or `error!` based on the error variant's `log_level()`,
/// then bumps the error metric counter via `stat_error()`.
///
/// Accepts the same structured-field syntax as tracing macros:
///   `log_stat_error!(err)`
///   `log_stat_error!(err, token=%tok, path=%p)`
///   `log_stat_error!(err, ctx = &context)`
///   `log_stat_error!(err, ctx = &context, batch_size = batch.batch.len())`
#[macro_export]
macro_rules! log_stat_error {
    // No fields
    ($err:expr) => {
        $crate::log_stat_error!(@emit $err,)
    };
    // With Context, no extra fields
    ($err:expr, ctx = $ctx:expr) => {
        $crate::log_stat_error!(@emit_ctx $err, $ctx,)
    };
    // With Context + extra trailing fields
    ($err:expr, ctx = $ctx:expr, $($extra:tt)+) => {
        $crate::log_stat_error!(@emit_ctx $err, $ctx, $($extra)+)
    };
    // Manual fields only (no Context)
    ($err:expr, $($fields:tt)+) => {
        $crate::log_stat_error!(@emit $err, $($fields)+)
    };
    // Internal: emit without Context
    (@emit $err:expr, $($fields:tt)*) => {{
        let err = &$err;
        let msg = format!("{}: {}", err.tag(), err);
        match err.log_level() {
            ::tracing::Level::WARN => ::tracing::warn!($($fields)* "{}", msg),
            _ => ::tracing::error!($($fields)* "{}", msg),
        }
        err.stat_error();
    }};
    // Internal: emit with Context auto-expansion
    (@emit_ctx $err:expr, $ctx:expr, $($extra:tt)*) => {{
        let err = &$err;
        let ctx = &$ctx;
        let msg = format!("{}: {}", err.tag(), err);
        match err.log_level() {
            ::tracing::Level::WARN => ::tracing::warn!(
                token = %ctx.api_token,
                request_id = %ctx.request_id,
                sdk_info = %ctx.sdk_info,
                attempt = ctx.attempt,
                client_timestamp = %ctx.client_timestamp,
                server_received_at = %ctx.server_received_at,
                user_agent = %ctx.user_agent,
                content_type = %ctx.content_type,
                content_encoding = ?ctx.content_encoding,
                client_ip = %ctx.client_ip,
                method = %ctx.method,
                query = ?ctx.query,
                path = %ctx.path,
                $($extra)*
                "{}", msg
            ),
            _ => ::tracing::error!(
                token = %ctx.api_token,
                request_id = %ctx.request_id,
                sdk_info = %ctx.sdk_info,
                attempt = ctx.attempt,
                client_timestamp = %ctx.client_timestamp,
                server_received_at = %ctx.server_received_at,
                user_agent = %ctx.user_agent,
                content_type = %ctx.content_type,
                content_encoding = ?ctx.content_encoding,
                client_ip = %ctx.client_ip,
                method = %ctx.method,
                query = ?ctx.query,
                path = %ctx.path,
                $($extra)*
                "{}", msg
            ),
        }
        err.stat_error();
    }};
}

impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Error::RequestParsingError(e.to_string())
    }
}

impl IntoResponse for Error {
    fn into_response(self) -> Response {
        let status = self.status_code();
        let headers = self.response_headers();
        let body = ErrorResponse::new(&self);
        (status, headers, Json(body)).into_response()
    }
}
