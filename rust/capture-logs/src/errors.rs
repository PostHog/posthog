//! Error responses for the ingest handlers.
//!
//! Handlers previously returned `(StatusCode, Json<Value>)`, which cannot carry a header. This
//! type exists so a rejection can also set `Retry-After`, which is the difference between an
//! OTLP client backing off and an OTLP client throwing the batch away: per the OTLP spec
//! (<https://opentelemetry.io/docs/specs/otlp/#failures-1>) only 429, 502, 503 and 504 are
//! retryable, and on a retryable response the client honours `Retry-After` when it is present.

use axum::{
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde_json::json;

#[derive(Debug)]
pub struct ApiError {
    status: StatusCode,
    message: String,
    retry_after_seconds: Option<u64>,
}

impl ApiError {
    pub fn new(status: StatusCode, message: impl Into<String>) -> Self {
        Self {
            status,
            message: message.into(),
            retry_after_seconds: None,
        }
    }

    pub fn unauthorized(message: impl Into<String>) -> Self {
        Self::new(StatusCode::UNAUTHORIZED, message)
    }

    pub fn bad_request(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, message)
    }

    pub fn payload_too_large(message: impl Into<String>) -> Self {
        Self::new(StatusCode::PAYLOAD_TOO_LARGE, message)
    }

    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, message)
    }

    /// 429 rather than a 4xx the client must treat as permanent: the data is refused now but
    /// will be accepted again once the quota resets, so the sender should hold off, not give up.
    pub fn quota_exceeded(message: impl Into<String>, retry_after_seconds: u64) -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            message: message.into(),
            retry_after_seconds: Some(retry_after_seconds),
        }
    }

    pub fn status(&self) -> StatusCode {
        self.status
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let mut response = (self.status, Json(json!({ "error": self.message }))).into_response();
        if let Some(seconds) = self.retry_after_seconds {
            response
                .headers_mut()
                .insert(header::RETRY_AFTER, HeaderValue::from(seconds));
        }
        response
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn retry_after(error: ApiError) -> Option<String> {
        error
            .into_response()
            .headers()
            .get(header::RETRY_AFTER)
            .map(|v| v.to_str().unwrap().to_string())
    }

    #[test]
    fn quota_exceeded_is_retryable_with_a_retry_after() {
        let error = ApiError::quota_exceeded("over quota", 900);

        let response = error.into_response();
        assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(
            response
                .headers()
                .get(header::RETRY_AFTER)
                .and_then(|v| v.to_str().ok()),
            Some("900")
        );
    }

    #[test]
    fn non_retryable_rejections_carry_no_retry_after() {
        // A `Retry-After` on a status the OTLP spec calls permanent would be ignored at best
        // and misread as "retry this" at worst, so it must not be set.
        assert_eq!(retry_after(ApiError::unauthorized("nope")), None);
        assert_eq!(retry_after(ApiError::bad_request("nope")), None);
        assert_eq!(retry_after(ApiError::internal("nope")), None);
    }

    #[tokio::test]
    async fn body_keeps_the_error_envelope_clients_already_parse() {
        let response = ApiError::unauthorized("No token provided").into_response();

        let body = axum::body::to_bytes(response.into_body(), 1024)
            .await
            .unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&body).unwrap(),
            json!({"error": "No token provided"})
        );
    }
}
