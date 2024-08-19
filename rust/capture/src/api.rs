use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use time::OffsetDateTime;
use uuid::Uuid;

use crate::token::InvalidTokenReason;

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum CaptureResponseCode {
    Ok = 1,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct CaptureResponse {
    pub status: CaptureResponseCode,
}

#[derive(Error, Debug)]
pub enum CaptureError {
    #[error("failed to decode request: {0}")]
    RequestDecodingError(String),
    #[error("failed to parse request: {0}")]
    RequestParsingError(#[from] serde_json::Error),

    #[error("request holds no event")]
    EmptyBatch,
    #[error("event submitted with an empty event name")]
    MissingEventName,
    #[error("event submitted with an empty distinct_id")]
    EmptyDistinctId,
    #[error("event submitted without a distinct_id")]
    MissingDistinctId,
    #[error("replay event submitted without snapshot data")]
    MissingSnapshotData,
    #[error("replay event submitted without session id")]
    MissingSessionId,
    #[error("replay event submitted without window id")]
    MissingWindowId,

    #[error("event submitted without an api_key")]
    NoTokenError,
    #[error("batch submitted with inconsistent api_key values")]
    MultipleTokensError,
    #[error("API key is not valid: {0}")]
    TokenValidationError(#[from] InvalidTokenReason),

    #[error("transient error, please retry")]
    RetryableSinkError,
    #[error("maximum event size exceeded")]
    EventTooBig,
    #[error("invalid event could not be processed")]
    NonRetryableSinkError,

    #[error("billing limit reached")]
    BillingLimit,

    #[error("rate limited")]
    RateLimited,
}

impl IntoResponse for CaptureError {
    fn into_response(self) -> Response {
        match self {
            CaptureError::RequestDecodingError(_)
            | CaptureError::RequestParsingError(_)
            | CaptureError::EmptyBatch
            | CaptureError::MissingEventName
            | CaptureError::EmptyDistinctId
            | CaptureError::MissingDistinctId
            | CaptureError::EventTooBig
            | CaptureError::NonRetryableSinkError
            | CaptureError::MissingSessionId
            | CaptureError::MissingWindowId
            | CaptureError::MissingSnapshotData => (StatusCode::BAD_REQUEST, self.to_string()),

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

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub enum DataType {
    AnalyticsMain,
    AnalyticsHistorical,
    ClientIngestionWarning,
    HeatmapMain,
    ExceptionMain,
    SnapshotMain,
}
#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct ProcessedEvent {
    #[serde(skip_serializing)]
    pub data_type: DataType,
    pub uuid: Uuid,
    pub distinct_id: String,
    pub ip: String,
    pub data: String,
    pub now: String,
    #[serde(
        with = "time::serde::rfc3339::option",
        skip_serializing_if = "Option::is_none"
    )]
    pub sent_at: Option<OffsetDateTime>,
    pub token: String,
    #[serde(skip_serializing)]
    pub session_id: Option<String>,
}

impl ProcessedEvent {
    pub fn key(&self) -> String {
        format!("{}:{}", self.token, self.distinct_id)
    }
}
