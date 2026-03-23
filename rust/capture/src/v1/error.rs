use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use metrics::counter;
use serde::Serialize;
use thiserror::Error;
use tracing::Level;

const ERROR_METRIC_KEY: &str = "capture_v1_analytics_error";

#[derive(Debug, Clone, Serialize)]
pub struct ErrorResponse {
    #[serde(rename = "type")]
    pub error_type: String,
    pub code: String,
    pub detail: String,
}

impl ErrorResponse {
    fn new(error: &Error) -> Self {
        Self {
            error_type: error.tag().to_string(),
            code: error.status_code().as_str().to_string(),
            detail: error.to_string(),
        }
    }
}

#[derive(Debug, Error)]
pub enum Error {
    #[error("not implemented")]
    NotImplemented,
}

impl Error {
    pub fn tag(&self) -> &'static str {
        match self {
            Self::NotImplemented => "not_implemented",
        }
    }

    pub fn log_level(&self) -> Level {
        match self {
            Self::NotImplemented => Level::ERROR,
        }
    }

    fn level_tag(&self) -> &'static str {
        match self.log_level() {
            Level::WARN => "warn",
            _ => "error",
        }
    }

    pub fn log_error(&self) {
        match self.log_level() {
            Level::WARN => tracing::warn!("{self}"),
            _ => tracing::error!("{self}"),
        }
    }

    pub fn stat_error(&self) {
        let tags = [("error", self.tag()), ("level", self.level_tag())];
        counter!(ERROR_METRIC_KEY, &tags).increment(1);
    }

    pub fn status_code(&self) -> StatusCode {
        match self {
            Self::NotImplemented => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }
}

impl IntoResponse for Error {
    fn into_response(self) -> Response {
        let body = ErrorResponse::new(&self);
        (self.status_code(), Json(body)).into_response()
    }
}
