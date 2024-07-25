use std::collections::HashMap;

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::database::CustomDatabaseError;
use crate::redis::CustomRedisError;

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum FlagsResponseCode {
    Ok = 1,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlagsResponse {
    pub error_while_computing_flags: bool,
    // TODO: better typing here, support bool responses
    pub feature_flags: HashMap<String, String>,
}

#[derive(Error, Debug)]
pub enum FlagError {
    #[error("failed to decode request: {0}")]
    RequestDecodingError(String),
    #[error("failed to parse request: {0}")]
    RequestParsingError(#[from] serde_json::Error),

    #[error("Empty distinct_id in request")]
    EmptyDistinctId,
    #[error("No distinct_id in request")]
    MissingDistinctId,

    #[error("No api_key in request")]
    NoTokenError,
    #[error("API key is not valid")]
    TokenValidationError,

    #[error("rate limited")]
    RateLimited,

    #[error("failed to parse redis cache data")]
    DataParsingError,
    #[error("redis unavailable")]
    RedisUnavailable,
    #[error("database unavailable")]
    DatabaseUnavailable,
    #[error("Timed out while fetching data")]
    TimeoutError,
    // TODO: Consider splitting top-level errors (that are returned to the client)
    // and FlagMatchingError, like timeouterror which we can gracefully handle.
    // This will make the `into_response` a lot clearer as well, since it wouldn't
    // have arbitrary errors that actually never make it to the client.
}

impl IntoResponse for FlagError {
    fn into_response(self) -> Response {
        match self {
            FlagError::RequestDecodingError(_)
            | FlagError::RequestParsingError(_)
            | FlagError::EmptyDistinctId
            | FlagError::MissingDistinctId => (StatusCode::BAD_REQUEST, self.to_string()),

            FlagError::NoTokenError | FlagError::TokenValidationError => {
                (StatusCode::UNAUTHORIZED, self.to_string())
            }

            FlagError::RateLimited => (StatusCode::TOO_MANY_REQUESTS, self.to_string()),

            FlagError::DataParsingError
            | FlagError::RedisUnavailable
            | FlagError::DatabaseUnavailable
            | FlagError::TimeoutError => (StatusCode::SERVICE_UNAVAILABLE, self.to_string()),
        }
        .into_response()
    }
}

impl From<CustomRedisError> for FlagError {
    fn from(e: CustomRedisError) -> Self {
        match e {
            CustomRedisError::NotFound => FlagError::TokenValidationError,
            CustomRedisError::PickleError(e) => {
                tracing::error!("failed to fetch data: {}", e);
                FlagError::DataParsingError
            }
            CustomRedisError::Timeout(_) => FlagError::TimeoutError,
            CustomRedisError::Other(e) => {
                tracing::error!("Unknown redis error: {}", e);
                FlagError::RedisUnavailable
            }
        }
    }
}

impl From<CustomDatabaseError> for FlagError {
    fn from(e: CustomDatabaseError) -> Self {
        match e {
            CustomDatabaseError::NotFound => FlagError::TokenValidationError,
            CustomDatabaseError::Other(_) => {
                tracing::error!("failed to get connection: {}", e);
                FlagError::DatabaseUnavailable
            }
            CustomDatabaseError::Timeout(_) => FlagError::TimeoutError,
        }
    }
}

impl From<sqlx::Error> for FlagError {
    fn from(e: sqlx::Error) -> Self {
        // TODO: Be more precise with error handling here
        tracing::error!("sqlx error: {}", e);
        println!("sqlx error: {}", e);
        match e {
            sqlx::Error::RowNotFound => FlagError::TokenValidationError,
            _ => FlagError::DatabaseUnavailable,
        }
    }
}
