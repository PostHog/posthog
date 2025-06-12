use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use common_cookieless::CookielessManagerError;
use common_database::CustomDatabaseError;
use common_redis::CustomRedisError;
use thiserror::Error;

use crate::utils::graph_utils::DependencyType;

#[derive(Error, Debug)]
pub enum ClientFacingError {
    #[error("Invalid request: {0}")]
    BadRequest(String),
    #[error("Unauthorized: {0}")]
    Unauthorized(String),
    #[error("Rate limited")]
    RateLimited,
    #[error("billing limit reached")]
    BillingLimit,
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
    #[error("Row not found in postgres")]
    RowNotFound,
    #[error("failed to parse redis cache data")]
    RedisDataParsingError,
    #[error("failed to deserialize filters")]
    DeserializeFiltersError,
    #[error("failed to update redis cache")]
    CacheUpdateError,
    #[error("redis unavailable")]
    RedisUnavailable,
    #[error("database unavailable")]
    DatabaseUnavailable,
    #[error("Database error: {0}")]
    DatabaseError(String),
    #[error("Timed out while fetching data")]
    TimeoutError,
    #[error("No group type mappings")]
    NoGroupTypeMappings,
    #[error("Dependency of type {0} with id {1} not found")]
    DependencyNotFound(DependencyType, i64),
    #[error("Failed to parse cohort filters")]
    CohortFiltersParsingError,
    #[error("Dependency cycle detected: {0} id {1} starts the cycle")]
    DependencyCycle(DependencyType, i64),
    #[error("Person not found")]
    PersonNotFound,
    #[error("Person properties not found")]
    PropertiesNotInCache,
    #[error("Static cohort matches not cached")]
    StaticCohortMatchesNotCached,
    #[error(transparent)]
    CookielessError(#[from] CookielessManagerError),
}

impl IntoResponse for FlagError {
    fn into_response(self) -> Response {
        match self {
            FlagError::ClientFacing(err) => match err {
                ClientFacingError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg),
                ClientFacingError::Unauthorized(msg) => (StatusCode::UNAUTHORIZED, msg),
                ClientFacingError::BillingLimit => (StatusCode::PAYMENT_REQUIRED, "Billing limit reached. Please upgrade your plan.".to_string()),
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
            FlagError::RedisDataParsingError => {
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
            FlagError::DeserializeFiltersError => {
                tracing::error!("Failed to deserialize filters");
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "Failed to deserialize property filters. This is likely a temporary issue. Please try again later.".to_string(),
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
            FlagError::DatabaseError(msg) => {
                tracing::error!("Database error: {}", msg);
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "A database error occurred. Please try again later or contact support if the problem persists.".to_string(),
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
            FlagError::RowNotFound => {
                tracing::error!("Row not found in postgres: {:?}", self);
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "The requested row was not found in the database. Please try again later or contact support if the problem persists.".to_string(),
                )
            }
            FlagError::DependencyNotFound(dependency_type, dependency_id) => {
                tracing::error!("Dependency of type {dependency_type} with id {dependency_id} not found");
                (StatusCode::INTERNAL_SERVER_ERROR, format!("Dependency of type {dependency_type} with id {dependency_id} not found"))
            }
            FlagError::CohortFiltersParsingError => {
                tracing::error!("Failed to parse cohort filters: {:?}", self);
                (StatusCode::INTERNAL_SERVER_ERROR, "Failed to parse cohort filters. Please try again later or contact support if the problem persists.".to_string())
            }
            FlagError::DependencyCycle(dependency_type, cycle_start_id) => {
                tracing::error!("{} dependency cycle: {:?}", dependency_type, cycle_start_id);
                (StatusCode::INTERNAL_SERVER_ERROR, format!("Dependency cycle detected: {dependency_type} id {cycle_start_id} starts the cycle"))
            }
            FlagError::PersonNotFound => {
                (StatusCode::BAD_REQUEST, "Person not found. Please check your distinct_id and try again.".to_string())
            }
            FlagError::PropertiesNotInCache => {
                (StatusCode::BAD_REQUEST, "Person properties not found. Please check your distinct_id and try again.".to_string())
            }
            FlagError::StaticCohortMatchesNotCached => {
                (StatusCode::BAD_REQUEST, "Static cohort matches not cached. Please check your distinct_id and try again.".to_string())
            }
            FlagError::CookielessError(err) => {
                match err {
                    // 400 Bad Request errors - client-side issues
                    CookielessManagerError::MissingProperty(prop) =>
                        (StatusCode::BAD_REQUEST, format!("Missing required property: {}", prop)),
                    CookielessManagerError::UrlParseError(e) =>
                        (StatusCode::BAD_REQUEST, format!("Invalid URL: {}", e)),
                    CookielessManagerError::InvalidTimestamp(msg) =>
                        (StatusCode::BAD_REQUEST, format!("Invalid timestamp: {}", msg)),

                    // 500 Internal Server Error - server-side issues
                    err @ (CookielessManagerError::HashError(_) |
                          CookielessManagerError::ChronoError(_) |
                          CookielessManagerError::RedisError(_) |
                          CookielessManagerError::SaltCacheError(_) |
                          CookielessManagerError::InvalidIdentifyCount(_)) => {
                        tracing::error!("Internal cookieless error: {}", err);
                        (StatusCode::INTERNAL_SERVER_ERROR, "An internal error occurred while processing your request.".to_string())
                    }
                }
            }
        }
        .into_response()
    }
}

impl From<CustomRedisError> for FlagError {
    fn from(e: CustomRedisError) -> Self {
        match e {
            CustomRedisError::NotFound => FlagError::TokenValidationError,
            CustomRedisError::ParseError(_) => FlagError::RedisDataParsingError,
            CustomRedisError::Timeout => FlagError::TimeoutError,
            CustomRedisError::Other(_) => FlagError::RedisUnavailable,
        }
    }
}

impl From<CustomDatabaseError> for FlagError {
    fn from(e: CustomDatabaseError) -> Self {
        match e {
            CustomDatabaseError::Other(_) => FlagError::DatabaseUnavailable,
            CustomDatabaseError::Timeout(_) => FlagError::TimeoutError,
        }
    }
}

impl From<sqlx::Error> for FlagError {
    fn from(e: sqlx::Error) -> Self {
        match e {
            sqlx::Error::RowNotFound => FlagError::RowNotFound,
            _ => FlagError::DatabaseError(e.to_string()),
        }
    }
}
