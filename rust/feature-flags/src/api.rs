use std::collections::HashMap;

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::{Deserialize, Serialize};
use thiserror::Error;

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

            FlagError::DataParsingError | FlagError::RedisUnavailable => {
                (StatusCode::SERVICE_UNAVAILABLE, self.to_string())
            }
        }
        .into_response()
    }
}
