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
    #[error("IP rate limited")]
    IpRateLimited,
    #[error("Token rate limited")]
    TokenRateLimited,
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
    /// Returns (error_code, status_code) for this error.
    ///
    /// This consolidates error classification in one place to ensure consistency
    /// between error codes and HTTP status codes, and makes adding new error
    /// variants easier (only one match statement to update).
    fn error_metadata(&self) -> (&'static str, u16) {
        match self {
            // Client-facing errors
            FlagError::ClientFacing(ClientFacingError::BadRequest(_)) => ("bad_request", 400),
            FlagError::ClientFacing(ClientFacingError::Unauthorized(_)) => ("unauthorized", 401),
            FlagError::ClientFacing(ClientFacingError::RateLimited) => ("rate_limited", 429),
            FlagError::ClientFacing(ClientFacingError::IpRateLimited) => ("ip_rate_limited", 429),
            FlagError::ClientFacing(ClientFacingError::TokenRateLimited) => {
                ("token_rate_limited", 429)
            }
            FlagError::ClientFacing(ClientFacingError::BillingLimit) => ("billing_limit", 402),
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable) => {
                ("service_unavailable", 503)
            }

            // Request parsing errors (400)
            FlagError::RequestDecodingError(_) => ("request_decoding_error", 400),
            FlagError::RequestParsingError(_) => ("request_parsing_error", 400),
            FlagError::MissingDistinctId => ("missing_distinct_id", 400),
            FlagError::PersonNotFound => ("person_not_found", 400),
            FlagError::PropertiesNotInCache => ("properties_not_in_cache", 400),
            FlagError::StaticCohortMatchesNotCached => ("static_cohort_not_cached", 400),

            // Authentication errors (401)
            FlagError::NoTokenError => ("missing_token", 401),
            FlagError::TokenValidationError => ("invalid_token", 401),
            FlagError::PersonalApiKeyInvalid(_) => ("personal_api_key_invalid", 401),
            FlagError::SecretApiTokenInvalid => ("secret_api_token_invalid", 401),
            FlagError::NoAuthenticationProvided => ("no_authentication", 401),

            // Internal server errors (500)
            FlagError::Internal(_) => ("internal_error", 500),
            FlagError::DeserializeFiltersError => ("deserialize_filters_error", 500),
            FlagError::DatabaseError(_, _) => ("database_error", 500),
            FlagError::NoGroupTypeMappings => ("no_group_type_mappings", 500),
            FlagError::RowNotFound => ("row_not_found", 500),
            FlagError::DependencyNotFound(_, _) => ("dependency_not_found", 500),
            FlagError::CohortFiltersParsingError => ("cohort_filters_parsing_error", 500),
            FlagError::DependencyCycle(_, _) => ("dependency_cycle", 500),
            FlagError::DataParsingError => ("data_parsing_error", 500),

            // Service unavailable errors (503)
            FlagError::RedisDataParsingError => ("redis_parsing_error", 503),
            FlagError::RedisUnavailable => ("redis_unavailable", 503),
            FlagError::DatabaseUnavailable => ("database_unavailable", 503),
            FlagError::TimeoutError(_) => ("timeout", 503),
            FlagError::CacheMiss => ("cache_miss", 503),

            // Cookieless errors (mixed)
            FlagError::CookielessError(err) => match err {
                CookielessManagerError::MissingProperty(_)
                | CookielessManagerError::UrlParseError(_)
                | CookielessManagerError::InvalidTimestamp(_) => ("cookieless_error", 400),
                _ => ("cookieless_error", 500),
            },
        }
    }

    /// Returns a short error code for canonical logging.
    pub fn error_code(&self) -> &'static str {
        self.error_metadata().0
    }

    /// Returns the HTTP status code for this error.
    pub fn status_code(&self) -> u16 {
        self.error_metadata().1
    }

    pub fn is_5xx(&self) -> bool {
        let status = match self {
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable) => {
                StatusCode::SERVICE_UNAVAILABLE
            }
            FlagError::ClientFacing(_) => return false, // All other ClientFacing are 4XX
            FlagError::Internal(_)
            | FlagError::DeserializeFiltersError
            | FlagError::DatabaseError(_, _)
            | FlagError::NoGroupTypeMappings
            | FlagError::RowNotFound
            | FlagError::DependencyNotFound(_, _)
            | FlagError::CohortFiltersParsingError
            | FlagError::DependencyCycle(_, _)
            | FlagError::DataParsingError => StatusCode::INTERNAL_SERVER_ERROR,

            FlagError::RedisDataParsingError
            | FlagError::RedisUnavailable
            | FlagError::DatabaseUnavailable
            | FlagError::TimeoutError(_)
            | FlagError::CacheMiss => StatusCode::SERVICE_UNAVAILABLE,

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
                ClientFacingError::RateLimited
                | ClientFacingError::IpRateLimited
                | ClientFacingError::TokenRateLimited => {
                    let response = AuthenticationErrorResponse {
                        error_type: "validation_error".to_string(),
                        code: "rate_limit_exceeded".to_string(),
                        detail: "Rate limit exceeded".to_string(),
                        attr: None,
                    };
                    return (StatusCode::TOO_MANY_REQUESTS, Json(response)).into_response();
                }
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
            CustomRedisError::NotFound => FlagError::TokenValidationError,
            CustomRedisError::ParseError(_) => FlagError::RedisDataParsingError,
            CustomRedisError::Timeout => FlagError::TimeoutError(Some("Redis timeout".to_string())),
            CustomRedisError::InvalidConfiguration(_) | CustomRedisError::Redis(_) => {
                FlagError::RedisUnavailable
            }
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
        // Test that Redis timeout errors are converted to FlagError::TimeoutError
        let redis_timeout: FlagError = CustomRedisError::Timeout.into();
        assert!(
            matches!(redis_timeout, FlagError::TimeoutError(Some(ref timeout_type)) if timeout_type == "Redis timeout")
        );
    }

    #[test]
    fn test_error_codes_are_non_empty() {
        // Verify all error codes are non-empty strings
        let errors: Vec<FlagError> = vec![
            FlagError::ClientFacing(ClientFacingError::BadRequest("test".to_string())),
            FlagError::ClientFacing(ClientFacingError::Unauthorized("test".to_string())),
            FlagError::ClientFacing(ClientFacingError::RateLimited),
            FlagError::ClientFacing(ClientFacingError::IpRateLimited),
            FlagError::ClientFacing(ClientFacingError::TokenRateLimited),
            FlagError::ClientFacing(ClientFacingError::BillingLimit),
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable),
            FlagError::Internal("test".to_string()),
            FlagError::RequestDecodingError("test".to_string()),
            serde_json::from_str::<String>("invalid json")
                .unwrap_err()
                .into(), // RequestParsingError
            FlagError::MissingDistinctId,
            FlagError::NoTokenError,
            FlagError::TokenValidationError,
            FlagError::PersonalApiKeyInvalid("test".to_string()),
            FlagError::SecretApiTokenInvalid,
            FlagError::NoAuthenticationProvided,
            FlagError::RowNotFound,
            FlagError::RedisDataParsingError,
            FlagError::DeserializeFiltersError,
            FlagError::RedisUnavailable,
            FlagError::DatabaseUnavailable,
            FlagError::DatabaseError(sqlx::Error::RowNotFound, Some("test context".to_string())),
            FlagError::TimeoutError(None),
            FlagError::NoGroupTypeMappings,
            FlagError::DependencyNotFound(DependencyType::Flag, 1),
            FlagError::DependencyCycle(DependencyType::Cohort, 2),
            FlagError::CohortFiltersParsingError,
            FlagError::PersonNotFound,
            FlagError::PropertiesNotInCache,
            FlagError::StaticCohortMatchesNotCached,
            FlagError::CacheMiss,
            FlagError::DataParsingError,
            CookielessManagerError::MissingProperty("test".to_string()).into(), // CookielessError
        ];

        for error in errors {
            let code = error.error_code();
            assert!(
                !code.is_empty(),
                "Error code should not be empty for {error:?}"
            );
            assert!(
                !code.contains(' '),
                "Error code should not contain spaces: {code}"
            );
        }
    }

    #[test]
    fn test_status_codes_match_http_semantics() {
        // 4xx errors (client errors)
        assert_eq!(
            FlagError::ClientFacing(ClientFacingError::BadRequest("".into())).status_code(),
            400
        );
        assert_eq!(
            FlagError::ClientFacing(ClientFacingError::Unauthorized("".into())).status_code(),
            401
        );
        assert_eq!(
            FlagError::ClientFacing(ClientFacingError::BillingLimit).status_code(),
            402
        );
        assert_eq!(
            FlagError::ClientFacing(ClientFacingError::RateLimited).status_code(),
            429
        );
        assert_eq!(FlagError::MissingDistinctId.status_code(), 400);
        assert_eq!(FlagError::NoTokenError.status_code(), 401);
        assert_eq!(FlagError::TokenValidationError.status_code(), 401);
        assert_eq!(FlagError::PersonNotFound.status_code(), 400);

        // 5xx errors (server errors)
        assert_eq!(FlagError::Internal("".into()).status_code(), 500);
        assert_eq!(FlagError::DatabaseUnavailable.status_code(), 503);
        assert_eq!(FlagError::RedisUnavailable.status_code(), 503);
        assert_eq!(FlagError::TimeoutError(None).status_code(), 503);
        assert_eq!(
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable).status_code(),
            503
        );
        assert_eq!(FlagError::RowNotFound.status_code(), 500);
    }

    #[test]
    fn test_status_code_ranges() {
        // All client-facing errors except ServiceUnavailable should be 4xx
        let client_4xx_errors = vec![
            FlagError::ClientFacing(ClientFacingError::BadRequest("".into())),
            FlagError::ClientFacing(ClientFacingError::Unauthorized("".into())),
            FlagError::ClientFacing(ClientFacingError::RateLimited),
            FlagError::ClientFacing(ClientFacingError::BillingLimit),
        ];
        for error in client_4xx_errors {
            let status = error.status_code();
            assert!(
                (400..500).contains(&status),
                "Expected 4xx for {error:?}, got {status}"
            );
        }

        // Server errors should be 5xx
        let server_errors = vec![
            FlagError::Internal("".into()),
            FlagError::DeserializeFiltersError,
            FlagError::NoGroupTypeMappings,
            FlagError::RowNotFound,
            FlagError::CohortFiltersParsingError,
            FlagError::DataParsingError,
        ];
        for error in server_errors {
            let status = error.status_code();
            assert!(status >= 500, "Expected 5xx for {error:?}, got {status}");
        }
    }

    #[test]
    fn test_error_code_consistency_with_is_5xx() {
        // Verify that status_code() >= 500 matches is_5xx() for ALL 5xx errors
        let errors_5xx = vec![
            FlagError::Internal("test".to_string()),
            FlagError::DeserializeFiltersError,
            FlagError::DatabaseError(sqlx::Error::RowNotFound, None),
            FlagError::NoGroupTypeMappings,
            FlagError::RowNotFound,
            FlagError::DependencyNotFound(DependencyType::Flag, 1),
            FlagError::CohortFiltersParsingError,
            FlagError::DependencyCycle(DependencyType::Cohort, 2),
            FlagError::DataParsingError,
            FlagError::RedisDataParsingError,
            FlagError::RedisUnavailable,
            FlagError::DatabaseUnavailable,
            FlagError::TimeoutError(None),
            FlagError::CacheMiss,
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable),
        ];

        for error in errors_5xx {
            let is_5xx = error.is_5xx();
            let status = error.status_code();
            assert!(
                is_5xx,
                "is_5xx() should be true for {error:?} (status={status})"
            );
            assert!(
                status >= 500,
                "status_code() should be >= 500 for {error:?}, got {status}"
            );
        }
    }

    #[test]
    fn test_specific_error_codes() {
        // Verify specific error codes match expected values
        assert_eq!(
            FlagError::ClientFacing(ClientFacingError::RateLimited).error_code(),
            "rate_limited"
        );
        assert_eq!(FlagError::NoTokenError.error_code(), "missing_token");
        assert_eq!(
            FlagError::TokenValidationError.error_code(),
            "invalid_token"
        );
        assert_eq!(
            FlagError::MissingDistinctId.error_code(),
            "missing_distinct_id"
        );
        assert_eq!(
            FlagError::TimeoutError(Some("pool".to_string())).error_code(),
            "timeout"
        );
        assert_eq!(
            FlagError::DatabaseUnavailable.error_code(),
            "database_unavailable"
        );
        assert_eq!(
            FlagError::RedisUnavailable.error_code(),
            "redis_unavailable"
        );
    }

    #[test]
    fn test_error_codes_are_unique() {
        use std::collections::HashSet;

        // All error variants that should have unique error codes
        let errors: Vec<FlagError> = vec![
            FlagError::ClientFacing(ClientFacingError::BadRequest("test".to_string())),
            FlagError::ClientFacing(ClientFacingError::Unauthorized("test".to_string())),
            FlagError::ClientFacing(ClientFacingError::RateLimited),
            FlagError::ClientFacing(ClientFacingError::IpRateLimited),
            FlagError::ClientFacing(ClientFacingError::TokenRateLimited),
            FlagError::ClientFacing(ClientFacingError::BillingLimit),
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable),
            FlagError::Internal("test".to_string()),
            FlagError::RequestDecodingError("test".to_string()),
            serde_json::from_str::<String>("invalid json")
                .unwrap_err()
                .into(), // RequestParsingError
            FlagError::MissingDistinctId,
            FlagError::NoTokenError,
            FlagError::TokenValidationError,
            FlagError::PersonalApiKeyInvalid("test".to_string()),
            FlagError::SecretApiTokenInvalid,
            FlagError::NoAuthenticationProvided,
            FlagError::RowNotFound,
            FlagError::RedisDataParsingError,
            FlagError::DeserializeFiltersError,
            FlagError::RedisUnavailable,
            FlagError::DatabaseUnavailable,
            FlagError::DatabaseError(sqlx::Error::RowNotFound, Some("test context".to_string())),
            FlagError::TimeoutError(None),
            FlagError::NoGroupTypeMappings,
            FlagError::DependencyNotFound(DependencyType::Flag, 1),
            FlagError::DependencyCycle(DependencyType::Cohort, 2),
            FlagError::CohortFiltersParsingError,
            FlagError::PersonNotFound,
            FlagError::PropertiesNotInCache,
            FlagError::StaticCohortMatchesNotCached,
            FlagError::CacheMiss,
            FlagError::DataParsingError,
            CookielessManagerError::MissingProperty("test".to_string()).into(),
        ];

        let mut seen_codes: HashSet<&'static str> = HashSet::new();
        for error in &errors {
            let code = error.error_code();
            assert!(
                seen_codes.insert(code),
                "Duplicate error code '{code}' found for {error:?}"
            );
        }
    }
}
