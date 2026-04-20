use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use metrics::counter;
use serde::Serialize;
use thiserror::Error;
use tracing::Level;

use crate::v1::analytics::constants::{ACCEPT_ENCODING_ALL, ACCEPT_JSON, DEFAULT_RETRY_AFTER_SECS};
use crate::v1::constants::{CAPTURE_V1_ERROR_METRIC, CAPTURE_V1_UNKNOWN_PATH};
use crate::v1::context::Context;

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
    #[error("distinct_id is a known illegal value: {0}")]
    InvalidDistinctId(String),
    #[error("event submitted without a uuid")]
    MissingEventUuid,
    #[error("duplicate event uuid: {0}")]
    DuplicateEventUuid(String),
    #[error("event submitted with invalid timestamp")]
    InvalidEventTimestamp,
    #[error("event properties is not a JSON object")]
    MalformedEventProperties,
    #[error("$performance_event is not accepted")]
    DroppedPerformanceEvent,

    // 401 - authentication_error
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

    // 402 - billing_error (non-retryable, unlike 429)
    #[error("billing limit exceeded")]
    BillingLimitExceeded,

    // 429 - rate_limit_error
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
            Self::InvalidDistinctId(_) => "invalid_distinct_id",
            Self::MissingEventUuid => "missing_event_uuid",
            Self::DuplicateEventUuid(_) => "duplicate_event_uuid",
            Self::InvalidEventTimestamp => "invalid_event_timestamp",
            Self::MalformedEventProperties => "malformed_event_properties",
            Self::DroppedPerformanceEvent => "dropped_performance_event",
            Self::RequestTimeout => "request_timeout",
            Self::BodyReadTimeout(_) => "body_read_timeout",
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
            Self::InvalidApiToken(_) => "The provided API token is not valid.".to_string(),
            Self::BillingLimitExceeded => "Billing quota exceeded. Events are being dropped. Upgrade your plan to resume ingestion.".to_string(),
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
        match self {
            Self::BillingLimitExceeded => "https://posthog.com/docs/billing/limits",
            _ => "https://posthog.com/docs/api",
        }
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
            | Self::InvalidDistinctId(_)
            | Self::MissingEventUuid
            | Self::DuplicateEventUuid(_)
            | Self::InvalidEventTimestamp
            | Self::MalformedEventProperties
            | Self::DroppedPerformanceEvent
            | Self::RequestTimeout
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

    pub(crate) fn stat_error(&self, ctx: Option<&Context>) {
        let path = ctx
            .map(|c| c.path.clone())
            .unwrap_or_else(|| CAPTURE_V1_UNKNOWN_PATH.to_owned());
        let status = self.status_code().as_str().to_owned();
        counter!(
            CAPTURE_V1_ERROR_METRIC,
            "error" => self.tag(),
            "level" => self.level_tag(),
            "path" => path,
            "status_code" => status,
        )
        .increment(1);
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
            | Self::InvalidDistinctId(_)
            | Self::MissingEventUuid
            | Self::DuplicateEventUuid(_)
            | Self::InvalidEventTimestamp
            | Self::MalformedEventProperties
            | Self::DroppedPerformanceEvent => StatusCode::BAD_REQUEST,

            Self::RequestTimeout | Self::BodyReadTimeout(_) => StatusCode::REQUEST_TIMEOUT,

            Self::InvalidApiToken(_) => StatusCode::UNAUTHORIZED,

            Self::PayloadTooLarge(_) => StatusCode::PAYLOAD_TOO_LARGE,

            Self::UnsupportedContentType(_) | Self::UnsupportedEncoding(_) => {
                StatusCode::UNSUPPORTED_MEDIA_TYPE
            }

            Self::BillingLimitExceeded => StatusCode::PAYMENT_REQUIRED,

            Self::RateLimited(_) => StatusCode::TOO_MANY_REQUESTS,

            Self::InternalError(_) => StatusCode::INTERNAL_SERVER_ERROR,

            Self::ServiceUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,

            Self::GatewayTimeout => StatusCode::GATEWAY_TIMEOUT,
        }
    }

    pub fn response_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(header::ACCEPT, ACCEPT_JSON);
        headers.insert(header::ACCEPT_ENCODING, ACCEPT_ENCODING_ALL);

        if let Self::RateLimited(_) = self {
            headers.insert(header::RETRY_AFTER, DEFAULT_RETRY_AFTER_SECS);
        }

        headers
    }
}

/// Emits a `tracing::event!` at the given level with all `v1::Context`
/// fields expanded as structured log tags.
///
/// Usage:
///   `ctx_log!(Level::INFO, context, "message")`
///   `ctx_log!(Level::WARN, context, extra_field = %val, "message {x}")`
#[macro_export]
macro_rules! ctx_log {
    ($level:expr, $ctx:expr, $($rest:tt)+) => {{
        let ctx = &$ctx;
        ::tracing::event!(
            $level,
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
            $($rest)+
        )
    }};
}

/// Logs at the error's `log_level()` with all `v1::Context` fields,
/// then bumps the error metric counter via `stat_error()`.
///
/// Always requires a `&Context`. For the pre-Context header-error path,
/// inline the tracing call directly.
///
/// Usage:
///   `log_stat_error!(err, &context)`
///   `log_stat_error!(err, &context, batch_size = batch.batch.len())`
#[macro_export]
macro_rules! log_stat_error {
    ($err:expr, $ctx:expr) => {
        $crate::log_stat_error!(@impl $err, $ctx,)
    };
    ($err:expr, $ctx:expr, $($extra:tt)+) => {
        $crate::log_stat_error!(@impl $err, $ctx, $($extra)+)
    };
    (@impl $err:expr, $ctx:expr, $($extra:tt)*) => {{
        let err = &$err;
        match err.log_level() {
            ::tracing::Level::WARN =>
                $crate::ctx_log!(::tracing::Level::WARN, $ctx,
                    error_tag = %err.tag(),
                    error = %err,
                    $($extra)*
                    "{err:#}"),
            _ =>
                $crate::ctx_log!(::tracing::Level::ERROR, $ctx,
                    error_tag = %err.tag(),
                    error = %err,
                    $($extra)*
                    "{err:#}"),
        }
        err.stat_error(Some(&$ctx));
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

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::to_bytes;
    use axum::http::header::RETRY_AFTER;

    async fn response_body(resp: Response) -> serde_json::Value {
        let bytes = to_bytes(resp.into_body(), 65_536).await.unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    #[tokio::test]
    async fn bad_request_status_and_body_shape() {
        let err = Error::EmptyBatch;
        let expected_status = err.status_code();
        let expected_tag = err.tag().to_string();
        let resp = err.into_response();
        assert_eq!(resp.status(), expected_status);
        let body = response_body(resp).await;
        assert_eq!(body["error"], expected_tag);
        assert!(body["error_description"].is_string());
        assert!(body["error_uri"].is_string());
    }

    #[tokio::test]
    async fn rate_limited_includes_retry_after() {
        let err = Error::RateLimited("too many requests".into());
        let resp = err.into_response();
        assert_eq!(resp.status(), StatusCode::TOO_MANY_REQUESTS);
        assert!(resp.headers().contains_key(RETRY_AFTER));
    }

    #[tokio::test]
    async fn unauthorized_status() {
        let err = Error::InvalidApiToken("bad".into());
        let resp = err.into_response();
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
        let body = response_body(resp).await;
        assert_eq!(body["error"], "invalid_api_token");
    }

    #[tokio::test]
    async fn internal_error_status() {
        let err = Error::InternalError("boom".into());
        let resp = err.into_response();
        assert_eq!(resp.status(), StatusCode::INTERNAL_SERVER_ERROR);
    }

    #[tokio::test]
    async fn billing_limit_custom_error_uri() {
        let err = Error::BillingLimitExceeded;
        let resp = err.into_response();
        assert_eq!(resp.status(), StatusCode::PAYMENT_REQUIRED);
        let body = response_body(resp).await;
        assert_eq!(body["error_uri"], "https://posthog.com/docs/billing/limits");
    }

    #[tokio::test]
    async fn gateway_timeout_status() {
        let err = Error::GatewayTimeout;
        let resp = err.into_response();
        assert_eq!(resp.status(), StatusCode::GATEWAY_TIMEOUT);
    }
}
