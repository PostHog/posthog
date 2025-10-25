use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::token::InvalidTokenReason;

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum CaptureResponseCode {
    Ok = 1,
    NoContent = 2,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct CaptureResponse {
    pub status: CaptureResponseCode,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
}

impl IntoResponse for CaptureResponse {
    fn into_response(self) -> Response {
        match self.status {
            CaptureResponseCode::NoContent => StatusCode::NO_CONTENT.into_response(),
            CaptureResponseCode::Ok => (StatusCode::OK, Json(self)).into_response(),
        }
    }
}

#[derive(Clone, Error, Debug)]
pub enum CaptureError {
    #[error("failed to decode request: {0}")]
    RequestDecodingError(String),
    #[error("failed to parse request: {0}")]
    RequestParsingError(String),
    #[error("failed to hydrate events from request: {0}")]
    RequestHydrationError(String),

    #[error("request holds no event")]
    EmptyBatch,
    #[error("request missing data payload")]
    EmptyPayload,
    #[error("event submitted with an empty event name")]
    MissingEventName,
    #[error("event submitted without a distinct_id")]
    MissingDistinctId,
    #[error("event submitted with invalid cookieless mode")]
    InvalidCookielessMode,
    #[error("event submitted with invalid timestamp")]
    InvalidTimestamp,
    #[error("replay event submitted without snapshot data")]
    MissingSnapshotData,
    #[error("replay event submitted without session id")]
    MissingSessionId,
    #[error("replay event submitted without window id")]
    MissingWindowId,
    #[error("replay event has invalid session id")]
    InvalidSessionId,

    #[error("event submitted without an api_key")]
    NoTokenError,
    #[error("batch submitted with inconsistent api_key values")]
    MultipleTokensError,
    #[error("API key is not valid: {0}")]
    TokenValidationError(#[from] InvalidTokenReason),

    #[error("transient error, please retry")]
    RetryableSinkError,
    #[error("maximum event size exceeded: {0}")]
    EventTooBig(String),
    #[error("invalid event could not be processed")]
    NonRetryableSinkError,

    #[error("billing limit reached")]
    BillingLimit,

    #[error("rate limited")]
    RateLimited,

    #[error("payload empty after filtering invalid event types")]
    EmptyPayloadFiltered,
}

impl From<serde_json::Error> for CaptureError {
    fn from(e: serde_json::Error) -> Self {
        CaptureError::RequestParsingError(e.to_string())
    }
}

impl CaptureError {
    pub fn to_metric_tag(&self) -> &'static str {
        match self {
            CaptureError::RequestDecodingError(_) => "req_decoding",
            CaptureError::RequestParsingError(_) => "req_parsing",
            CaptureError::RequestHydrationError(_) => "req_hydration",
            CaptureError::EmptyBatch => "empty_batch",
            CaptureError::EmptyPayload => "empty_payload",
            CaptureError::MissingEventName => "no_event_name",
            CaptureError::MissingDistinctId => "no_distinct_id",
            CaptureError::InvalidCookielessMode => "invalid_cookieless",
            CaptureError::InvalidTimestamp => "invalid_timestamp",
            CaptureError::MissingSnapshotData => "no_snapshot",
            CaptureError::MissingSessionId => "no_session_id",
            CaptureError::MissingWindowId => "no_window_id",
            CaptureError::InvalidSessionId => "invalid_session",
            CaptureError::NoTokenError => "no_token",
            CaptureError::MultipleTokensError => "multiple_tokens",
            CaptureError::TokenValidationError(_) => "invalid_token",
            CaptureError::RetryableSinkError => "retryable_sink",
            CaptureError::EventTooBig(_) => "oversize_event",
            CaptureError::NonRetryableSinkError => "non_retry_sink",
            CaptureError::BillingLimit => "billing_limit",
            CaptureError::RateLimited => "rate_limited",
            CaptureError::EmptyPayloadFiltered => "empty_filtered_payload",
        }
    }
}

impl IntoResponse for CaptureError {
    fn into_response(self) -> Response {
        match self {
            CaptureError::RequestDecodingError(_)
            | CaptureError::RequestParsingError(_)
            | CaptureError::RequestHydrationError(_)
            | CaptureError::EmptyBatch
            | CaptureError::EmptyPayload
            | CaptureError::MissingEventName
            | CaptureError::MissingDistinctId
            | CaptureError::InvalidCookielessMode
            | CaptureError::InvalidTimestamp
            | CaptureError::NonRetryableSinkError
            | CaptureError::MissingSessionId
            | CaptureError::MissingWindowId
            | CaptureError::InvalidSessionId
            | CaptureError::EmptyPayloadFiltered
            | CaptureError::MissingSnapshotData => (StatusCode::BAD_REQUEST, self.to_string()),

            CaptureError::EventTooBig(_) => (StatusCode::PAYLOAD_TOO_LARGE, self.to_string()),

            CaptureError::NoTokenError
            | CaptureError::MultipleTokensError
            | CaptureError::TokenValidationError(_) => (StatusCode::UNAUTHORIZED, self.to_string()),

            CaptureError::RetryableSinkError => (StatusCode::SERVICE_UNAVAILABLE, self.to_string()),

            CaptureError::BillingLimit | CaptureError::RateLimited => {
                (StatusCode::TOO_MANY_REQUESTS, self.to_string())
            }
        }
        .into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;

    #[test]
    fn test_capture_response_into_response_ok() {
        // Test Ok response
        let response = CaptureResponse {
            status: CaptureResponseCode::Ok,
            quota_limited: None,
        };
        let response = response.into_response();
        assert_eq!(response.status(), StatusCode::OK);
    }

    #[test]
    fn test_capture_response_into_response_no_content() {
        // Test NoContent response
        let response = CaptureResponse {
            status: CaptureResponseCode::NoContent,
            quota_limited: None,
        };
        let response = response.into_response();
        assert_eq!(response.status(), StatusCode::NO_CONTENT);
    }
}
