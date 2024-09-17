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
#[serde(untagged)]
pub enum FlagValue {
    Boolean(bool),
    String(String),
}

// TODO the following two types are kinda general, maybe we should move them to a shared module
#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum BooleanOrStringObject {
    Boolean(bool),
    Object(HashMap<String, String>),
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum BooleanOrBooleanObject {
    Boolean(bool),
    Object(HashMap<String, bool>),
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlagsResponse {
    pub error_while_computing_flags: bool,
    pub feature_flags: HashMap<String, FlagValue>,
    // TODO support the other fields in the payload
    // pub config: HashMap<String, bool>,
    // pub toolbar_params: HashMap<String, String>,
    // pub is_authenticated: bool,
    // pub supported_compression: Vec<String>,
    // pub session_recording: bool,
    // pub feature_flag_payloads: HashMap<String, String>,
    // pub capture_performance: BooleanOrBooleanObject,
    // #[serde(rename = "autocapture_opt_out")]
    // pub autocapture_opt_out: bool,
    // pub autocapture_exceptions: BooleanOrStringObject,
    // pub surveys: bool,
    // pub heatmaps: bool,
    // pub site_apps: Vec<String>,
}

#[derive(Error, Debug)]
pub enum ClientFacingError {
    #[error("Invalid request: {0}")]
    BadRequest(String),
    #[error("Unauthorized: {0}")]
    Unauthorized(String),
    #[error("Rate limited")]
    RateLimited,
    #[error("Service unavailable")]
    ServiceUnavailable,
}

#[derive(Error, Debug)]
pub enum FlagError {
    #[error(transparent)]
    ClientFacing(#[from] ClientFacingError),
    #[error("Internal error: {0}")]
    Internal(String),
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
    #[error("failed to parse redis cache data")]
    DataParsingError,
    #[error("failed to update redis cache")]
    CacheUpdateError,
    #[error("redis unavailable")]
    RedisUnavailable,
    #[error("database unavailable")]
    DatabaseUnavailable,
    #[error("Timed out while fetching data")]
    TimeoutError,
    #[error("No group type mappings")]
    NoGroupTypeMappings,
}

impl IntoResponse for FlagError {
    fn into_response(self) -> Response {
        match self {
            FlagError::ClientFacing(err) => match err {
                ClientFacingError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg),
                ClientFacingError::Unauthorized(msg) => (StatusCode::UNAUTHORIZED, msg),
                ClientFacingError::RateLimited => (StatusCode::TOO_MANY_REQUESTS, "Rate limit exceeded. Please reduce your request frequency and try again later.".to_string()),
                ClientFacingError::ServiceUnavailable => (StatusCode::SERVICE_UNAVAILABLE, "Service is currently unavailable. Please try again later.".to_string()),
            },
            FlagError::Internal(msg) => {
                tracing::error!("Internal server error: {}", msg);
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "An internal server error occurred. Please try again later or contact support if the problem persists.".to_string(),
                )
            }
            FlagError::RequestDecodingError(msg) => {
                (StatusCode::BAD_REQUEST, format!("Failed to decode request: {}. Please check your request format and try again.", msg))
            }
            FlagError::RequestParsingError(err) => {
                (StatusCode::BAD_REQUEST, format!("Failed to parse request: {}. Please ensure your request is properly formatted and all required fields are present.", err))
            }
            FlagError::EmptyDistinctId => {
                (StatusCode::BAD_REQUEST, "The distinct_id field cannot be empty. Please provide a valid identifier.".to_string())
            }
            FlagError::MissingDistinctId => {
                (StatusCode::BAD_REQUEST, "The distinct_id field is missing from the request. Please include a valid identifier.".to_string())
            }
            FlagError::NoTokenError => {
                (StatusCode::UNAUTHORIZED, "No API token provided. Please include a valid API token in your request.".to_string())
            }
            FlagError::TokenValidationError => {
                (StatusCode::UNAUTHORIZED, "The provided API key is invalid or has expired. Please check your API key and try again.".to_string())
            }
            FlagError::DataParsingError => {
                tracing::error!("Data parsing error: {:?}", self);
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Failed to parse internal data. This is likely a temporary issue. Please try again later.".to_string(),
                )
            }
            FlagError::CacheUpdateError => {
                tracing::error!("Cache update error: {:?}", self);
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Failed to update internal cache. This is likely a temporary issue. Please try again later.".to_string(),
                )
            }
            FlagError::RedisUnavailable => {
                tracing::error!("Redis unavailable: {:?}", self);
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Our cache service is currently unavailable. This is likely a temporary issue. Please try again later.".to_string(),
                )
            }
            FlagError::DatabaseUnavailable => {
                tracing::error!("Database unavailable: {:?}", self);
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Our database service is currently unavailable. This is likely a temporary issue. Please try again later.".to_string(),
                )
            }
            FlagError::TimeoutError => {
                tracing::error!("Timeout error: {:?}", self);
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "The request timed out. This could be due to high load or network issues. Please try again later.".to_string(),
                )
            }
            FlagError::NoGroupTypeMappings => {
                tracing::error!("No group type mappings: {:?}", self);
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "No group type mappings found. This is likely a configuration issue. Please contact support.".to_string(),
                )
            }
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
