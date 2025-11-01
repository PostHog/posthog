use axum::http::StatusCode;
use axum::response::{IntoResponse, Json, Response};
use common_cookieless::CookielessManagerError;
use common_database::{extract_timeout_type, is_timeout_error, CustomDatabaseError};
use common_hypercache::HyperCacheError;
use common_redis::CustomRedisError;
use serde::Serialize;
use thiserror::Error;

use crate::utils::graph_utils::DependencyType;

/// Structured error response matching Django REST Framework's format
#[derive(Debug, Serialize)]
pub struct AuthenticationErrorResponse {
    #[serde(rename = "type")]
    pub error_type: String,
    pub code: String,
    pub detail: String,
    pub attr: Option<String>,
}

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
    #[error("No distinct_id in request")]
    MissingDistinctId,
    #[error("No api_key in request")]
    NoTokenError,
    #[error("API key is not valid")]
    TokenValidationError,
    #[error("Personal API key found in request {0} is invalid")]
    PersonalApiKeyInvalid(String),
    #[error("Secret API token is invalid")]
    SecretApiTokenInvalid,
    #[error("No authentication credentials provided")]
    NoAuthenticationProvided,
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
    DatabaseError(sqlx::Error, Option<String>),
    /// Timeout error with optional type classification.
    ///
    /// Valid timeout types include:
    /// - `"query_canceled"` - Statement timeout (PostgreSQL SQLSTATE 57014)
    /// - `"lock_not_available"` - Lock timeout (PostgreSQL SQLSTATE 55P03)
    /// - `"idle_in_transaction_timeout"` - Idle transaction timeout (PostgreSQL SQLSTATE 25P03)
    /// - `"pool_timeout"` - Connection pool acquisition timeout
    /// - `"io_timeout"` - Network/socket timeout
    /// - `"protocol_timeout"` - PostgreSQL protocol timeout
    /// - `"client_timeout"` - Client-side tokio::timeout wrapper
    /// - `"redis_timeout"` - Redis operation timeout
    /// - `"cache_timeout"` - Cache operation timeout
    /// - `"database_timeout"` - Generic database timeout (fallback when SQLSTATE unavailable)
    /// - `None` - Timeout occurred but specific type unknown
    #[error("Timed out while fetching data")]
    TimeoutError(Option<String>),
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
    #[error("Cache miss - data not found in cache")]
    CacheMiss,
    #[error("Failed to parse data")]
    DataParsingError,
    #[error(transparent)]
    CookielessError(#[from] CookielessManagerError),
}

impl FlagError {
    pub fn is_5xx(&self) -> bool {
        let status = match self {
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable) => {
                StatusCode::SERVICE_UNAVAILABLE
            }
            FlagError::ClientFacing(_) => return false, // All other ClientFacing are 4XX
            FlagError::Internal(_)
            | FlagError::CacheUpdateError
            | FlagError::DeserializeFiltersError
            | FlagError::DatabaseError(_, _)
            | FlagError::NoGroupTypeMappings
            | FlagError::RowNotFound
            | FlagError::DependencyNotFound(_, _)
            | FlagError::CohortFiltersParsingError
            | FlagError::DependencyCycle(_, _) => StatusCode::INTERNAL_SERVER_ERROR,

            FlagError::RedisDataParsingError
            | FlagError::RedisUnavailable
            | FlagError::DatabaseUnavailable
            | FlagError::TimeoutError(_) => StatusCode::SERVICE_UNAVAILABLE,

            FlagError::CookielessError(
                CookielessManagerError::HashError(_)
                | CookielessManagerError::ChronoError(_)
                | CookielessManagerError::RedisError(_, _)
                | CookielessManagerError::SaltCacheError(_)
                | CookielessManagerError::InvalidIdentifyCount(_),
            ) => StatusCode::INTERNAL_SERVER_ERROR,
            FlagError::CookielessError(_) => return false, // Other CookielessErrors are 4XX
            _ => return false,                             // Everything else is 4XX
        };
        status.is_server_error()
    }
}

impl IntoResponse for FlagError {
    fn into_response(self) -> Response {
        match self {
            FlagError::ClientFacing(err) => match err {
                ClientFacingError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg),
                ClientFacingError::Unauthorized(msg) => (StatusCode::UNAUTHORIZED, msg),
                ClientFacingError::BillingLimit => (StatusCode::PAYMENT_REQUIRED, "Billing limit reached. Please upgrade your plan.".to_string()),
                ClientFacingError::RateLimited => {
                    let response = AuthenticationErrorResponse {
                        error_type: "validation_error".to_string(),
                        code: "rate_limit_exceeded".to_string(),
                        detail: "Rate limit exceeded".to_string(),
                        attr: None,
                    };
                    return (StatusCode::TOO_MANY_REQUESTS, Json(response)).into_response();
                },
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
                (StatusCode::BAD_REQUEST, format!("Failed to decode request: {msg}. Please check your request format and try again."))
            }
            FlagError::RequestParsingError(err) => {
                (StatusCode::BAD_REQUEST, format!("Failed to parse request: {err}. Please ensure your request is properly formatted and all required fields are present."))
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
            FlagError::PersonalApiKeyInvalid(source) => {
                let response = AuthenticationErrorResponse {
                    error_type: "authentication_error".to_string(),
                    code: "authentication_failed".to_string(),
                    detail: format!("Personal API key found in request {source} is invalid."),
                    attr: None,
                };
                return (StatusCode::UNAUTHORIZED, Json(response)).into_response();
            }
            FlagError::SecretApiTokenInvalid => {
                let response = AuthenticationErrorResponse {
                    error_type: "authentication_error".to_string(),
                    code: "authentication_failed".to_string(),
                    detail: "Secret API token is invalid.".to_string(),
                    attr: None,
                };
                return (StatusCode::UNAUTHORIZED, Json(response)).into_response();
            }
            FlagError::NoAuthenticationProvided => {
                let response = AuthenticationErrorResponse {
                    error_type: "authentication_error".to_string(),
                    code: "not_authenticated".to_string(),
                    detail: "Authentication credentials were not provided.".to_string(),
                    attr: None,
                };
                return (StatusCode::UNAUTHORIZED, Json(response)).into_response();
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
            FlagError::DatabaseError(sqlx_error, context) => {
                if let Some(ctx) = context {
                    tracing::error!("Database error with context '{}': {}", ctx, sqlx_error);
                } else {
                    tracing::error!("Database error: {}", sqlx_error);
                }
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "A database error occurred. Please try again later or contact support if the problem persists.".to_string(),
                )
            }
            FlagError::TimeoutError(ref timeout_type) => {
                let timeout_desc = timeout_type.as_deref().unwrap_or("unknown type");
                tracing::error!("Timeout error ({}): {:?}", timeout_desc, self);
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
            FlagError::CacheMiss => {
                tracing::error!("Cache miss - required data not found in cache");
                (StatusCode::SERVICE_UNAVAILABLE, "Required data not found in cache. This is likely a temporary issue. Please try again later.".to_string())
            }
            FlagError::DataParsingError => {
                tracing::error!("Failed to parse data");
                (StatusCode::INTERNAL_SERVER_ERROR, "Failed to parse internal data. This is likely a temporary issue. Please try again later.".to_string())
            }
            FlagError::CookielessError(err) => {
                match err {
                    // 400 Bad Request errors - client-side issues
                    CookielessManagerError::MissingProperty(prop) => {
                        tracing::warn!("Cookieless missing property: {}", prop);
                        (StatusCode::BAD_REQUEST, format!("Missing required property: {prop}"))
                    },
                    CookielessManagerError::UrlParseError(e) => {
                        tracing::warn!("Cookieless URL parse error: {}", e);
                        (StatusCode::BAD_REQUEST, format!("Invalid URL: {e}"))
                    },
                    CookielessManagerError::InvalidTimestamp(msg) => {
                        tracing::warn!("Cookieless invalid timestamp: {}", msg);
                        (StatusCode::BAD_REQUEST, format!("Invalid timestamp: {msg}"))
                    },

                    // 500 Internal Server Error - server-side issues
                    err @ (CookielessManagerError::HashError(_) |
                          CookielessManagerError::ChronoError(_) |
                          CookielessManagerError::RedisError(_, _) |
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
            // NOTE: This mapping is used by legacy team_operations::fetch_team_from_redis_with_fallback
            // In that context, NotFound means the team token doesn't exist in cache, which is treated
            // as a token validation error. New code using ReadThroughCache should not rely on this.
            CustomRedisError::NotFound => FlagError::TokenValidationError,
            CustomRedisError::ParseError(_) => FlagError::RedisDataParsingError,
            CustomRedisError::Timeout => FlagError::TimeoutError(Some("redis_timeout".to_string())),
            CustomRedisError::Other(_) => FlagError::RedisUnavailable,
        }
    }
}

impl From<CustomDatabaseError> for FlagError {
    fn from(e: CustomDatabaseError) -> Self {
        match e {
            CustomDatabaseError::Timeout(_) => {
                FlagError::TimeoutError(Some("client_timeout".to_string()))
            }
            CustomDatabaseError::Other(sqlx_error) => {
                // Check if it's a timeout-related SQL error
                if is_timeout_error(&sqlx_error) {
                    FlagError::TimeoutError(
                        extract_timeout_type(&sqlx_error).map(|s| s.to_string()),
                    )
                } else {
                    FlagError::DatabaseUnavailable
                }
            }
        }
    }
}

impl From<sqlx::Error> for FlagError {
    fn from(e: sqlx::Error) -> Self {
        match e {
            sqlx::Error::RowNotFound => FlagError::RowNotFound,
            _ => {
                // Check if it's a timeout-related SQL error
                if is_timeout_error(&e) {
                    FlagError::TimeoutError(extract_timeout_type(&e).map(|s| s.to_string()))
                } else {
                    FlagError::DatabaseError(e, None)
                }
            }
        }
    }
}

impl From<HyperCacheError> for FlagError {
    fn from(e: HyperCacheError) -> Self {
        match e {
            HyperCacheError::CacheMiss => FlagError::CacheMiss,
            HyperCacheError::Redis(redis_error) => FlagError::from(redis_error),
            HyperCacheError::S3(_) => FlagError::CacheMiss,
            HyperCacheError::Json(_) => FlagError::DataParsingError,
            HyperCacheError::Compression(_) => FlagError::DataParsingError,
            HyperCacheError::Timeout(_) => {
                FlagError::TimeoutError(Some("cache_timeout".to_string()))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{timeout, Duration};

    #[test]
    fn test_is_5xx() {
        // Test 5XX errors
        assert!(FlagError::Internal("test".to_string()).is_5xx());
        assert!(FlagError::CacheUpdateError.is_5xx());
        assert!(FlagError::DatabaseUnavailable.is_5xx());
        assert!(FlagError::RedisUnavailable.is_5xx());
        assert!(FlagError::TimeoutError(None).is_5xx());
        assert!(FlagError::ClientFacing(ClientFacingError::ServiceUnavailable).is_5xx());

        // Test 4XX errors
        assert!(
            !FlagError::ClientFacing(ClientFacingError::BadRequest("test".to_string())).is_5xx()
        );
        assert!(
            !FlagError::ClientFacing(ClientFacingError::Unauthorized("test".to_string())).is_5xx()
        );
        assert!(!FlagError::ClientFacing(ClientFacingError::RateLimited).is_5xx());
        assert!(!FlagError::ClientFacing(ClientFacingError::BillingLimit).is_5xx());
        assert!(!FlagError::MissingDistinctId.is_5xx());
        assert!(!FlagError::NoTokenError.is_5xx());
        assert!(!FlagError::TokenValidationError.is_5xx());
        assert!(!FlagError::PersonNotFound.is_5xx());
    }

    #[test]
    fn test_custom_database_error_conversion_timeout() {
        // Test that CustomDatabaseError::Timeout converts to FlagError::TimeoutError with client_timeout
        let rt = tokio::runtime::Runtime::new().unwrap();
        let elapsed_error = rt.block_on(async {
            timeout(
                Duration::from_nanos(1),
                tokio::time::sleep(Duration::from_secs(1)),
            )
            .await
            .unwrap_err()
        });

        let timeout_error = CustomDatabaseError::Timeout(elapsed_error);
        let flag_error: FlagError = timeout_error.into();
        assert!(
            matches!(flag_error, FlagError::TimeoutError(Some(ref timeout_type)) if timeout_type == "client_timeout")
        );
    }

    #[test]
    fn test_custom_database_error_conversion_sqlx_timeout() {
        // Test that sqlx timeout errors convert to FlagError::TimeoutError with pool_timeout
        let sqlx_timeout = CustomDatabaseError::Other(sqlx::Error::PoolTimedOut);
        let flag_error: FlagError = sqlx_timeout.into();
        assert!(
            matches!(flag_error, FlagError::TimeoutError(Some(ref timeout_type)) if timeout_type == "pool_timeout")
        );
    }

    #[test]
    fn test_custom_database_error_conversion_sqlx_non_timeout() {
        // Test that non-timeout sqlx errors convert to FlagError::DatabaseUnavailable
        let sqlx_error = CustomDatabaseError::Other(sqlx::Error::RowNotFound);
        let flag_error: FlagError = sqlx_error.into();
        assert!(matches!(flag_error, FlagError::DatabaseUnavailable));
    }

    #[test]
    fn test_direct_sqlx_timeout_conversion() {
        // Test that direct sqlx timeout errors convert to FlagError::TimeoutError with type
        let sqlx_timeout: FlagError = sqlx::Error::PoolTimedOut.into();
        assert!(
            matches!(sqlx_timeout, FlagError::TimeoutError(Some(ref timeout_type)) if timeout_type == "pool_timeout")
        );
    }

    #[test]
    fn test_direct_sqlx_non_timeout_conversion() {
        // Test that direct non-timeout sqlx errors are handled correctly
        let sqlx_error: FlagError = sqlx::Error::RowNotFound.into();
        assert!(matches!(sqlx_error, FlagError::RowNotFound));
    }

    #[test]
    fn test_redis_timeout_conversion() {
        // Test that Redis timeout errors include timeout type
        let redis_timeout: FlagError = CustomRedisError::Timeout.into();
        assert!(
            matches!(redis_timeout, FlagError::TimeoutError(Some(ref timeout_type)) if timeout_type == "redis_timeout")
        );
    }
}
