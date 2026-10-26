use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use metrics::{counter, Label};
use serde::Serialize;
use serde_json::error::Category;
use thiserror::Error;
use tracing::Level;

use crate::v1::analytics::constants::DEFAULT_RETRY_AFTER_SECS;
use crate::v1::analytics::lenient::FieldTypeError;
use crate::v1::constants::{CAPTURE_V1_ERROR_METRIC, CAPTURE_V1_UNKNOWN_PATH};
use crate::v1::context::RequestContext;

#[derive(Debug, Clone, Serialize)]
pub struct ErrorResponse {
    pub error: String,
    pub error_description: String,
    pub error_uri: String,
}

#[derive(Debug)]
pub enum ParseFailure {
    Json {
        /// Can quote request values: log it, never put it in a response.
        message: String,
        category: Category,
        line: usize,
        column: usize,
    },
    Field(FieldTypeError),
}

impl ParseFailure {
    fn description(&self) -> String {
        match self {
            Self::Json {
                category,
                line,
                column,
                ..
            } => {
                let what = match category {
                    Category::Syntax => "invalid JSON",
                    Category::Data => "wrong JSON type or value",
                    Category::Eof => "unexpected end of JSON",
                    Category::Io => "unreadable body",
                };
                format!("Failed to parse request body: {what} at line {line}, column {column}.")
            }
            Self::Field(field) => format!("Failed to parse request body: {field}."),
        }
    }
}

impl std::fmt::Display for ParseFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Json { message, .. } => f.write_str(message),
            Self::Field(field) => field.fmt(f),
        }
    }
}

impl From<serde_json::Error> for ParseFailure {
    fn from(e: serde_json::Error) -> Self {
        Self::Json {
            message: e.to_string(),
            category: e.classify(),
            line: e.line(),
            column: e.column(),
        }
    }
}

impl From<FieldTypeError> for ParseFailure {
    fn from(e: FieldTypeError) -> Self {
        Self::Field(e)
    }
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
    #[error("invalid query parameter: {0}")]
    InvalidQueryParam(String),
    #[error("request is missing required query parameters: {0:?}")]
    MissingQueryParam(Vec<String>),
    #[error("failed to decode request: {0}")]
    RequestDecodingError(String),
    #[error("failed to parse request: {0}")]
    RequestParsingError(ParseFailure),
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
    #[error("event uuid is not valid: {0}")]
    InvalidEventUuid(String),
    #[error("event submitted with invalid timestamp")]
    InvalidEventTimestamp,
    #[error("event properties is not a JSON object")]
    MalformedEventProperties,
    #[error("$performance_event is not accepted")]
    DroppedPerformanceEvent,

    // 401 - authentication_error
    #[error("missing Authorization header")]
    MissingAuthorization,
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

    // 402 - billing_error (non-retryable)
    #[error("billing limit exceeded")]
    BillingLimitExceeded,

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
            Self::InvalidQueryParam(_) => "invalid_query_param",
            Self::MissingQueryParam(_) => "missing_query_params",
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
            Self::InvalidEventUuid(_) => "invalid_event_uuid",
            Self::InvalidEventTimestamp => "invalid_event_timestamp",
            Self::MalformedEventProperties => "malformed_event_properties",
            Self::DroppedPerformanceEvent => "dropped_performance_event",
            Self::RequestTimeout => "request_timeout",
            Self::BodyReadTimeout(_) => "body_read_timeout",
            Self::MissingAuthorization => "missing_authorization",
            Self::InvalidApiToken(_) => "invalid_api_token",
            Self::PayloadTooLarge(_) => "payload_too_large",
            Self::UnsupportedContentType(_) => "unsupported_content_type",
            Self::UnsupportedEncoding(_) => "unsupported_encoding",
            Self::BillingLimitExceeded => "billing_limit_exceeded",
            Self::InternalError(_) => "internal_error",
            Self::ServiceUnavailable(_) => "service_unavailable",
            Self::GatewayTimeout => "gateway_timeout",
        }
    }

    pub fn description(&self) -> String {
        match self {
            Self::RequestDecodingError(_) => "Failed to decode request body.".to_string(),
            Self::RequestParsingError(failure) => failure.description(),
            Self::InvalidApiToken(_) => "The provided API token is not valid.".to_string(),
            Self::BillingLimitExceeded => "Billing quota exceeded. Events are being dropped. Upgrade your plan to resume ingestion.".to_string(),
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
            Self::BillingLimitExceeded => "https://posthog.com/docs/billing/limits-alerts",
            _ => "https://posthog.com/docs/api",
        }
    }

    pub fn log_level(&self) -> Level {
        match self {
            // 4xx client errors: warn
            Self::MissingRequiredHeaders(_)
            | Self::InvalidHeaderValue(_)
            | Self::InvalidQueryParam(_)
            | Self::MissingQueryParam(_)
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
            | Self::InvalidEventUuid(_)
            | Self::InvalidEventTimestamp
            | Self::MalformedEventProperties
            | Self::DroppedPerformanceEvent
            | Self::RequestTimeout
            | Self::MissingAuthorization
            | Self::InvalidApiToken(_)
            | Self::PayloadTooLarge(_)
            | Self::UnsupportedContentType(_)
            | Self::UnsupportedEncoding(_)
            | Self::BillingLimitExceeded => Level::WARN,

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

    pub(crate) fn stat_error(&self, ctx: Option<&RequestContext>) {
        let path = ctx.map(|c| c.path).unwrap_or(CAPTURE_V1_UNKNOWN_PATH);
        let mut labels = vec![
            Label::new("error", self.tag()),
            Label::new("level", self.level_tag()),
            Label::new("path", path),
            Label::new("status_code", self.status_code().as_str().to_owned()),
        ];
        // Field errors add bounded `field` and `kind` labels; sums by the existing labels are unchanged.
        if let Self::RequestParsingError(ParseFailure::Field(field)) = self {
            labels.push(Label::new("field", field.field));
            labels.push(Label::new("kind", field.kind.as_str()));
        }
        counter!(CAPTURE_V1_ERROR_METRIC, labels).increment(1);
    }

    pub fn status_code(&self) -> StatusCode {
        match self {
            Self::MissingRequiredHeaders(_)
            | Self::InvalidHeaderValue(_)
            | Self::InvalidQueryParam(_)
            | Self::MissingQueryParam(_)
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
            | Self::InvalidEventUuid(_)
            | Self::InvalidEventTimestamp
            | Self::MalformedEventProperties
            | Self::DroppedPerformanceEvent => StatusCode::BAD_REQUEST,

            Self::RequestTimeout | Self::BodyReadTimeout(_) => StatusCode::REQUEST_TIMEOUT,

            Self::MissingAuthorization | Self::InvalidApiToken(_) => StatusCode::UNAUTHORIZED,

            Self::PayloadTooLarge(_) => StatusCode::PAYLOAD_TOO_LARGE,

            Self::UnsupportedContentType(_) | Self::UnsupportedEncoding(_) => {
                StatusCode::UNSUPPORTED_MEDIA_TYPE
            }

            Self::BillingLimitExceeded => StatusCode::PAYMENT_REQUIRED,

            Self::InternalError(_) => StatusCode::INTERNAL_SERVER_ERROR,

            Self::ServiceUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,

            Self::GatewayTimeout => StatusCode::GATEWAY_TIMEOUT,
        }
    }

    pub fn response_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();

        // 402 (BillingLimitExceeded) is intentionally non-retryable per RFC, so no Retry-After.
        if matches!(
            self,
            Self::RequestTimeout
                | Self::BodyReadTimeout(_)
                | Self::InternalError(_)
                | Self::ServiceUnavailable(_)
                | Self::GatewayTimeout
        ) {
            headers.insert(header::RETRY_AFTER, DEFAULT_RETRY_AFTER_SECS);
        }

        headers
    }
}

/// Emits a `tracing::event!` at the given level with all `RequestContext`
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
            query = ?ctx.raw_query,
            path = %ctx.path,
            $($rest)+
        )
    }};
}

/// Logs at the error's `log_level()` with all `RequestContext` fields,
/// then bumps the error metric counter via `stat_error()`.
///
/// Always requires a context that derefs to `&RequestContext`. For the
/// pre-context header-error path, inline the tracing call directly.
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
        Error::RequestParsingError(e.into())
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
    use crate::v1::analytics::lenient::JsonKind;
    use axum::body::to_bytes;
    use axum::http::header::RETRY_AFTER;
    use rstest::rstest;

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

    #[test]
    fn parse_failure_logs_serde_message_but_describes_only_the_position() {
        let serde_err = serde_json::from_str::<Vec<u32>>(r#"["alice@example.com"]"#).unwrap_err();
        let err = Error::from(serde_err);

        assert!(err.to_string().contains("alice@example.com"));
        assert_eq!(
            err.description(),
            "Failed to parse request body: wrong JSON type or value at line 1, column 20."
        );
    }

    #[tokio::test]
    async fn billing_limit_custom_error_uri() {
        let err = Error::BillingLimitExceeded;
        let resp = err.into_response();
        assert_eq!(resp.status(), StatusCode::PAYMENT_REQUIRED);
        let body = response_body(resp).await;
        assert_eq!(
            body["error_uri"],
            "https://posthog.com/docs/billing/limits-alerts"
        );
    }

    #[tokio::test]
    async fn gateway_timeout_status() {
        let err = Error::GatewayTimeout;
        let resp = err.into_response();
        assert_eq!(resp.status(), StatusCode::GATEWAY_TIMEOUT);
    }

    #[rstest]
    #[case::request_timeout(Error::RequestTimeout, StatusCode::REQUEST_TIMEOUT)]
    #[case::body_read_timeout(Error::BodyReadTimeout(1024), StatusCode::REQUEST_TIMEOUT)]
    #[case::internal_error(Error::InternalError("boom".into()), StatusCode::INTERNAL_SERVER_ERROR)]
    #[case::service_unavailable(Error::ServiceUnavailable("nope".into()), StatusCode::SERVICE_UNAVAILABLE)]
    #[case::gateway_timeout(Error::GatewayTimeout, StatusCode::GATEWAY_TIMEOUT)]
    #[tokio::test]
    async fn retryable_errors_emit_retry_after_one_second(
        #[case] err: Error,
        #[case] expected_status: StatusCode,
    ) {
        let resp = err.into_response();
        assert_eq!(resp.status(), expected_status);
        let value = resp
            .headers()
            .get(RETRY_AFTER)
            .expect("Retry-After header must be present on retryable errors");
        assert_eq!(value.to_str().unwrap(), "1");
    }

    #[rstest]
    #[case::billing_limit(Error::BillingLimitExceeded)]
    #[case::invalid_api_token(Error::InvalidApiToken("bad".into()))]
    #[case::empty_batch(Error::EmptyBatch)]
    #[case::payload_too_large(Error::PayloadTooLarge("big".into()))]
    #[case::unsupported_content_type(Error::UnsupportedContentType("text/plain".into()))]
    #[case::invalid_query_param(Error::InvalidQueryParam("bad param".into()))]
    #[case::missing_query_param(Error::MissingQueryParam(vec!["foo".into()]))]
    #[tokio::test]
    async fn non_retryable_errors_omit_retry_after(#[case] err: Error) {
        let resp = err.into_response();
        assert!(
            !resp.headers().contains_key(RETRY_AFTER),
            "Retry-After must NOT be present on non-retryable errors (status {})",
            resp.status()
        );
    }

    #[rstest]
    #[case::invalid_query_param(
        Error::InvalidQueryParam("invalid query string: missing field `x`".into()),
        StatusCode::BAD_REQUEST,
        "invalid_query_param",
        "invalid query parameter: invalid query string: missing field `x`"
    )]
    #[case::missing_query_param(
        Error::MissingQueryParam(vec!["foo".into(), "bar".into()]),
        StatusCode::BAD_REQUEST,
        "missing_query_params",
        "request is missing required query parameters: [\"foo\", \"bar\"]"
    )]
    #[tokio::test]
    async fn query_param_errors_status_tag_and_description(
        #[case] err: Error,
        #[case] expected_status: StatusCode,
        #[case] expected_tag: &str,
        #[case] expected_description: &str,
    ) {
        assert_eq!(err.status_code(), expected_status);
        assert_eq!(err.tag(), expected_tag);
        let resp = err.into_response();
        assert_eq!(resp.status(), expected_status);
        let body = response_body(resp).await;
        assert_eq!(body["error"], expected_tag);
        assert_eq!(body["error_description"], expected_description);
    }

    fn error_metric_labels(err: &Error) -> Vec<(String, String)> {
        use metrics_util::debugging::{DebugValue, DebuggingRecorder};

        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        err.stat_error(None);

        let mut series: Vec<_> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, ..)| key.key().name() == CAPTURE_V1_ERROR_METRIC)
            .collect();
        assert_eq!(series.len(), 1);
        let (key, _, _, value) = series.remove(0);
        assert_eq!(value, DebugValue::Counter(1));
        let mut labels: Vec<_> = key
            .key()
            .labels()
            .map(|l| (l.key().to_owned(), l.value().to_owned()))
            .collect();
        labels.sort();
        labels
    }

    #[rstest]
    #[case::field_type_error(
        Error::RequestParsingError(ParseFailure::Field(FieldTypeError {
            index: Some(3),
            field: "distinct_id",
            kind: JsonKind::Number,
        })),
        &[("field", "distinct_id"), ("kind", "number")]
    )]
    #[case::missing_field(
        Error::RequestParsingError(ParseFailure::Field(FieldTypeError {
            index: None,
            field: "created_at",
            kind: JsonKind::Missing,
        })),
        &[("field", "created_at"), ("kind", "missing")]
    )]
    #[case::corrupt_json(
        Error::from(serde_json::from_str::<serde_json::Value>("{").unwrap_err()),
        &[]
    )]
    fn parse_error_metric_adds_field_labels_only_for_field_errors(
        #[case] err: Error,
        #[case] extra: &[(&str, &str)],
    ) {
        let labels = error_metric_labels(&err);

        let mut expected: Vec<(String, String)> = [
            ("error", "request_parsing_error"),
            ("level", err.level_tag()),
            ("path", CAPTURE_V1_UNKNOWN_PATH),
            ("status_code", "400"),
        ]
        .iter()
        .chain(extra)
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        expected.sort();
        assert_eq!(labels, expected);
    }
}
