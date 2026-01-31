use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum AppError {
    #[error("Authentication required")]
    AuthRequired,

    #[error("Invalid token")]
    InvalidToken,

    #[error("Token expired")]
    TokenExpired,

    #[error("Too many requests")]
    TooManyRequests,

    #[error("Forbidden: {0}")]
    Forbidden(String),

    #[error("Not found: {0}")]
    NotFound(String),

    #[error("Database error: {0}")]
    Database(#[from] sqlx::Error),

    #[error("ClickHouse error: {0}")]
    ClickHouse(#[from] clickhouse::error::Error),

    #[error("Kafka error: {0}")]
    Kafka(String),

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("Internal error: {0}")]
    Internal(String),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, message) = match &self {
            AppError::AuthRequired => (StatusCode::UNAUTHORIZED, "Authentication required"),
            AppError::InvalidToken => (StatusCode::UNAUTHORIZED, "Invalid token"),
            AppError::TokenExpired => (StatusCode::UNAUTHORIZED, "Token expired"),
            AppError::TooManyRequests => (StatusCode::TOO_MANY_REQUESTS, "Too many requests"),
            AppError::Forbidden(msg) => (StatusCode::FORBIDDEN, msg.as_str()),
            AppError::NotFound(msg) => (StatusCode::NOT_FOUND, msg.as_str()),
            AppError::Database(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Database error"),
            AppError::ClickHouse(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Storage error"),
            AppError::Kafka(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Messaging error"),
            AppError::Serialization(_) => (StatusCode::BAD_REQUEST, "Invalid request format"),
            AppError::Internal(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Internal error"),
        };

        tracing::error!(error = ?self, status = %status, "Request error");

        let body = Json(json!({
            "error": message,
            "code": status.as_u16(),
        }));

        (status, body).into_response()
    }
}

pub type Result<T> = std::result::Result<T, AppError>;
