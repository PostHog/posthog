use axum::http::StatusCode;
use axum::response::{IntoResponse, Json, Response};
use common_cookieless::{CookielessManagerError, SaltCacheError};
use common_database::{
    extract_timeout_type, is_timeout_error, is_transient_error, CustomDatabaseError,
};
use common_hypercache::HyperCacheError;
use common_redis::CustomRedisError;
use serde::Serialize;
use thiserror::Error;

use crate::utils::graph_utils::DependencyType;

/// Simplifies serde error messages for end-user consumption.
///
/// Serde errors can be verbose, listing all valid enum variants, e.g.:
/// "unknown variant `contains`, expected one of `exact`, `is_not`, `icontains`, ..."
///
/// This truncates at ", expected" to produce a simpler message:
/// "unknown variant `contains`"
///
/// Full details are logged server-side; this is just for the client response.
pub fn simplify_serde_error(error: &str) -> &str {
    error.split(", expected").next().unwrap_or(error)
}

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
    /// `code` is public: it ships as `reason.code` and as a metrics label.
    /// Named `cause` because thiserror would treat `source` as `#[source]`,
    /// which `anyhow::Error` cannot satisfy.
    #[error("{cause}")]
    InternalError {
        code: &'static str,
        cause: anyhow::Error,
    },
    #[error("{cause}")]
    Unavailable {
        code: &'static str,
        cause: anyhow::Error,
    },
    #[error("failed to decode request: {0}")]
    RequestDecodingError(String),
    #[error("Decompressed request body exceeds limit ({decompressed} > {limit} bytes)")]
    PayloadTooLarge { decompressed: usize, limit: usize },
    #[error("failed to parse request: {0}")]
    RequestParsingError(#[from] serde_json::Error),
    #[error("No distinct_id in request")]
    MissingDistinctId,
    #[error("No api_key in request")]
    NoTokenError,
    #[error("API key is not valid")]
    TokenValidationError,
    #[error("Personal API key is invalid")]
    PersonalApiKeyInvalid,
    #[error("Personal API key lacks required scopes")]
    PersonalApiKeyInsufficientScopes,
    #[error("Secret API token is invalid")]
    SecretApiTokenInvalid,
    #[error("No authentication credentials provided")]
    NoAuthenticationProvided,
    #[error("Row not found in postgres")]
    RowNotFound,
    #[error("database unavailable")]
    DatabaseUnavailable,
    #[error("Failed to fetch hash key override for experience continuity")]
    HashKeyOverrideError,
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
    #[error("Dependency of type {0} with id {1} not found")]
    DependencyNotFound(DependencyType, i64),
    #[error("Failed to parse cohort filters")]
    CohortFiltersParsingError,
    #[error("Dependency cycle detected: {0} id {1} starts the cycle")]
    DependencyCycle(DependencyType, i64),
    #[error("Rayon semaphore acquisition timed out after {0}ms")]
    RayonSemaphoreTimeout(u64),
    #[error(transparent)]
    CookielessError(#[from] CookielessManagerError),
    /// A stored remote-config payload could not be decrypted with any configured key (or no
    /// decryptor is configured at all). Distinct from `Internal` so the response is JSON, not
    /// plain text -- SDKs calling `remote_config` parse the body as JSON on every status code.
    #[error("failed to decrypt remote config payload: {0}")]
    RemoteConfigDecryptFailed(String),
}

/// Codes that `IntoResponse` branches on, so the constructor and the arm cannot
/// drift apart. The codes used at one site only stay inline: a single literal has
/// no second reference to disagree with.
pub(crate) const CODE_FLAG_DATA_PARSING: &str = "flag_data_parsing_error";
pub(crate) const CODE_PERSON_NOT_FOUND: &str = "person_not_found";

impl FlagError {
    /// The `Internal error: ` prefix reaches customers as the `$feature_flag_reason`
    /// event property, so changing it changes their data. `context` keeps the chain.
    pub fn internal(cause: impl Into<anyhow::Error>) -> Self {
        let cause = cause.into();
        let message = format!("Internal error: {cause}");
        FlagError::InternalError {
            code: "internal_error",
            cause: cause.context(message),
        }
    }

    /// Corrupt or mismatched data, so a 500 rather than a retryable 503.
    pub fn flag_data_parsing(details: impl std::fmt::Display) -> Self {
        FlagError::InternalError {
            code: CODE_FLAG_DATA_PARSING,
            cause: anyhow::anyhow!("Failed to parse flag data: {details}"),
        }
    }

    pub fn data_parsing(cause: impl Into<anyhow::Error>) -> Self {
        FlagError::InternalError {
            code: "data_parsing_error",
            cause: cause.into().context("Failed to parse data"),
        }
    }

    pub fn batch_evaluation_panicked() -> Self {
        FlagError::InternalError {
            code: "batch_evaluation_panicked",
            cause: anyhow::anyhow!("Parallel batch evaluation task panicked"),
        }
    }

    pub fn redis_unavailable(cause: impl Into<anyhow::Error>) -> Self {
        FlagError::Unavailable {
            code: "redis_unavailable",
            cause: cause.into().context("redis unavailable"),
        }
    }

    pub fn cache_miss() -> Self {
        FlagError::Unavailable {
            code: "cache_miss",
            cause: anyhow::anyhow!("Cache miss - data not found in cache"),
        }
    }

    pub fn person_not_found() -> Self {
        FlagError::Unavailable {
            code: CODE_PERSON_NOT_FOUND,
            cause: anyhow::anyhow!("Person not found"),
        }
    }

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
            FlagError::PayloadTooLarge { .. } => ("payload_too_large", 413),

            // Authentication errors (401)
            FlagError::NoTokenError => ("missing_token", 401),
            FlagError::TokenValidationError => ("invalid_token", 401),
            FlagError::PersonalApiKeyInvalid => ("personal_api_key_invalid", 401),
            FlagError::PersonalApiKeyInsufficientScopes => {
                ("personal_api_key_insufficient_scopes", 403)
            }
            FlagError::SecretApiTokenInvalid => ("secret_api_token_invalid", 401),
            FlagError::NoAuthenticationProvided => ("no_authentication", 401),

            // Bucketed errors carry their own stable code.
            FlagError::InternalError { code, .. } => (code, 500),
            FlagError::Unavailable { code, .. } => (code, 503),

            // Internal server errors (500)
            FlagError::DatabaseError(_, _) => ("database_error", 500),
            FlagError::RowNotFound => ("row_not_found", 500),
            FlagError::DependencyNotFound(_, _) => ("dependency_not_found", 500),
            FlagError::CohortFiltersParsingError => ("cohort_filters_parsing_error", 500),
            FlagError::DependencyCycle(_, _) => ("dependency_cycle", 500),
            FlagError::HashKeyOverrideError => ("hash_key_override_error", 500),
            FlagError::RayonSemaphoreTimeout(_) => ("rayon_semaphore_timeout", 504),
            FlagError::RemoteConfigDecryptFailed(_) => ("remote_config_decrypt_failed", 500),

            // Service unavailable errors (503) - transient issues, retry may help
            FlagError::DatabaseUnavailable => ("database_unavailable", 503),
            FlagError::TimeoutError(_) => ("timeout", 503),

            // Cookieless errors (mixed)
            FlagError::CookielessError(err) => match err {
                CookielessManagerError::MissingProperty(_)
                | CookielessManagerError::UrlParseError(_)
                | CookielessManagerError::InvalidTimestamp(_)
                | CookielessManagerError::SaltCacheError(SaltCacheError::DateOutOfRange) => {
                    ("cookieless_error", 400)
                }
                _ => ("cookieless_error", 500),
            },
        }
    }

    /// Whether this error definitively means the token does not map to any team.
    /// Transient infrastructure errors (timeouts, Redis/DB unavailable) return false
    /// to avoid poisoning the negative cache with valid tokens during outages.
    pub fn is_token_not_found(&self) -> bool {
        matches!(
            self,
            FlagError::TokenValidationError | FlagError::RowNotFound
        )
    }

    /// Returns a short error code for canonical logging.
    pub fn error_code(&self) -> &'static str {
        self.error_metadata().0
    }

    /// Returns the HTTP status code for this error.
    pub fn status_code(&self) -> u16 {
        self.error_metadata().1
    }

    /// Returns a granular error code for flag evaluation failures.
    /// This provides more specific error classification than `error_code()`,
    /// particularly for database errors where we can distinguish between
    /// timeouts, connection pool exhaustion, etc.
    /// Falls back to `error_code()` for variants that don't need extra granularity.
    pub fn evaluation_error_code(&self) -> String {
        match self {
            FlagError::DatabaseError(sqlx_error, context) => {
                let error_msg = sqlx_error.to_string();
                let context_msg = context.as_deref().unwrap_or("");

                if error_msg.contains("statement timeout") {
                    "timeout".to_string()
                } else if error_msg.contains("no more connections") {
                    "no_more_connections".to_string()
                } else if context_msg.contains("Failed to fetch conditions") {
                    "flag_condition_retry".to_string()
                } else if context_msg.contains("Failed to fetch group") {
                    "group_mapping_retry".to_string()
                } else if context_msg.contains("Database healthcheck failed") {
                    "healthcheck_failed".to_string()
                } else if error_msg.contains("query_wait_timeout") {
                    "query_wait_timeout".to_string()
                } else {
                    self.error_code().to_string()
                }
            }
            FlagError::TimeoutError(Some(t)) => format!("timeout:{t}"),
            FlagError::TimeoutError(None) => "timeout_error".to_string(),
            FlagError::DependencyNotFound(dependency_type, _) => match dependency_type {
                DependencyType::Cohort => "dependency_not_found_cohort".to_string(),
                DependencyType::Flag => "dependency_not_found_flag".to_string(),
            },
            FlagError::DependencyCycle(dependency_type, _) => match dependency_type {
                DependencyType::Cohort => "dependency_cycle_cohort".to_string(),
                DependencyType::Flag => "dependency_cycle_flag".to_string(),
            },
            _ => self.error_code().to_string(),
        }
    }

    /// Returns a human-readable description for flag evaluation failures.
    /// Provides detailed descriptions for variants where the `Display` impl
    /// is too technical, and falls back to `to_string()` (the `#[error]` message)
    /// for everything else.
    pub fn evaluation_error_description(&self) -> String {
        match self {
            FlagError::DatabaseError(sqlx_error, context) => {
                let error_msg = sqlx_error.to_string();
                let context_msg = context.as_deref().unwrap_or("");

                if error_msg.contains("statement timeout") {
                    "Database statement timed out".to_string()
                } else if error_msg.contains("no more connections") {
                    "Database connection pool exhausted".to_string()
                } else if context_msg.contains("Failed to fetch conditions") {
                    "Failed to fetch flag conditions".to_string()
                } else if context_msg.contains("Failed to fetch group") {
                    "Failed to fetch group mappings".to_string()
                } else if context_msg.contains("Database healthcheck failed") {
                    "Database healthcheck failed".to_string()
                } else if error_msg.contains("query_wait_timeout") {
                    "Query wait timeout exceeded".to_string()
                } else {
                    "Database connection error during evaluation".to_string()
                }
            }
            FlagError::TimeoutError(Some(t)) => format!("Timeout: {t}"),
            FlagError::DependencyNotFound(dependency_type, _) => match dependency_type {
                DependencyType::Cohort => "Cohort dependency not found".to_string(),
                DependencyType::Flag => "Flag dependency not found".to_string(),
            },
            FlagError::DependencyCycle(dependency_type, _) => match dependency_type {
                DependencyType::Cohort => "Cohort dependency cycle detected".to_string(),
                DependencyType::Flag => "Flag dependency cycle detected".to_string(),
            },
            _ => self.to_string(),
        }
    }

    pub fn is_5xx(&self) -> bool {
        self.status_code() >= 500
    }
}

impl IntoResponse for FlagError {
    fn into_response(self) -> Response {
        match self {
            FlagError::ClientFacing(err) => match err {
                ClientFacingError::BadRequest(msg) => (StatusCode::BAD_REQUEST, msg),
                ClientFacingError::Unauthorized(msg) => (StatusCode::UNAUTHORIZED, msg),
                ClientFacingError::BillingLimit => {
                    let response = AuthenticationErrorResponse {
                        error_type: "quota_limited".to_string(),
                        code: "payment_required".to_string(),
                        detail: "You have exceeded your feature flag request quota".to_string(),
                        attr: None,
                    };
                    return (StatusCode::PAYMENT_REQUIRED, Json(response)).into_response();
                }
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
            FlagError::InternalError { code, cause } => {
                tracing::error!(error_code = code, "Internal server error: {cause:?}");
                // Corrupt flag data will fail every retry, so this one names the
                // thing the customer can actually fix.
                let detail = if code == CODE_FLAG_DATA_PARSING {
                    "Failed to parse flag configuration data. This may indicate a misconfigured feature flag. Please check your flag definitions or contact support."
                } else {
                    "An internal server error occurred. Please try again later or contact support if the problem persists."
                };
                (StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
            }
            FlagError::Unavailable { code, cause } => {
                match code {
                    // A person row that has not landed yet is expected under
                    // replication lag, so it does not deserve an error line.
                    CODE_PERSON_NOT_FOUND => tracing::warn!(
                        error_code = code,
                        "Service dependency unavailable: {cause:?}"
                    ),
                    _ => tracing::error!(
                        error_code = code,
                        "Service dependency unavailable: {cause:?}"
                    ),
                }
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    "A service dependency is temporarily unavailable. This is likely a temporary issue. Please try again later.".to_string(),
                )
            }
            FlagError::RequestDecodingError(msg) => {
                (StatusCode::BAD_REQUEST, format!("Failed to decode request: {msg}. Please check your request format and try again."))
            }
            FlagError::PayloadTooLarge { decompressed, limit } => {
                tracing::warn!(decompressed, limit, "Decompressed request body exceeded cap");
                (
                    StatusCode::PAYLOAD_TOO_LARGE,
                    format!(
                        "Decompressed request body exceeded {limit} bytes (got {decompressed}). \
                         If this is a legitimate workload, contact PostHog support."
                    ),
                )
            }
            FlagError::RequestParsingError(err) => {
                (StatusCode::BAD_REQUEST, format!("Failed to parse request: {err}. Please ensure your request is properly formatted and all required fields are present."))
            }
            FlagError::MissingDistinctId => {
                (StatusCode::BAD_REQUEST, "The distinct_id field is missing from the request. Please include a valid identifier.".to_string())
            }
            FlagError::NoTokenError => {
                let response = AuthenticationErrorResponse {
                    error_type: "authentication_error".to_string(),
                    code: "not_authenticated".to_string(),
                    detail: "No API token provided. Please include a valid API token in your request.".to_string(),
                    attr: None,
                };
                return (StatusCode::UNAUTHORIZED, Json(response)).into_response();
            }
            FlagError::TokenValidationError => {
                let response = AuthenticationErrorResponse {
                    error_type: "authentication_error".to_string(),
                    code: "authentication_failed".to_string(),
                    detail: "The provided API key is invalid or has expired. Please check your API key and try again.".to_string(),
                    attr: None,
                };
                return (StatusCode::UNAUTHORIZED, Json(response)).into_response();
            }
            FlagError::PersonalApiKeyInvalid => {
                let response = AuthenticationErrorResponse {
                    error_type: "authentication_error".to_string(),
                    code: "authentication_failed".to_string(),
                    detail: "Personal API key is invalid.".to_string(),
                    attr: None,
                };
                return (StatusCode::UNAUTHORIZED, Json(response)).into_response();
            }
            FlagError::PersonalApiKeyInsufficientScopes => {
                let response = AuthenticationErrorResponse {
                    error_type: "authentication_error".to_string(),
                    code: "permission_denied".to_string(),
                    detail: "Personal API key lacks required scopes (feature_flag:read or feature_flag:write).".to_string(),
                    attr: None,
                };
                return (StatusCode::FORBIDDEN, Json(response)).into_response();
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
            FlagError::HashKeyOverrideError => {
                tracing::error!("Failed to fetch hash key override for experience continuity");
                (StatusCode::INTERNAL_SERVER_ERROR, "Failed to fetch hash key override for experience continuity. Please try again later.".to_string())
            }
            FlagError::RayonSemaphoreTimeout(ms) => {
                tracing::warn!("Rayon semaphore acquisition timed out after {}ms", ms);
                (StatusCode::GATEWAY_TIMEOUT, format!("Evaluation pool busy, timed out after {ms}ms. Please retry."))
            }
            FlagError::RemoteConfigDecryptFailed(_) => {
                // The failure is already logged with project_id/flag_key context at the source in
                // resolve_decrypted_payload; don't log it a second time here.
                let response = AuthenticationErrorResponse {
                    error_type: "server_error".to_string(),
                    code: "remote_config_decrypt_failed".to_string(),
                    detail: "Failed to decrypt the remote config payload. Please contact support if the problem persists.".to_string(),
                    attr: None,
                };
                return (StatusCode::INTERNAL_SERVER_ERROR, Json(response)).into_response();
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
                    // sent_at resolved to a date outside the salt-cache validity window
                    // (e.g. crawlers with frozen Date.now()) — bad input, not a server fault.
                    CookielessManagerError::SaltCacheError(SaltCacheError::DateOutOfRange) => {
                        tracing::warn!("Cookieless date out of range - sent_at outside salt-cache validity window");
                        (
                            StatusCode::BAD_REQUEST,
                            "Invalid sent_at: timestamp resolves to a date outside the accepted ingestion window".to_string(),
                        )
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

impl From<common_compression::CompressionError> for FlagError {
    fn from(e: common_compression::CompressionError) -> Self {
        match e {
            common_compression::CompressionError::OutputTooLarge {
                decompressed,
                limit,
            } => FlagError::PayloadTooLarge {
                decompressed,
                limit,
            },
            other => FlagError::RequestDecodingError(other.to_string()),
        }
    }
}

impl From<CustomRedisError> for FlagError {
    fn from(e: CustomRedisError) -> Self {
        match e {
            CustomRedisError::NotFound => FlagError::TokenValidationError,
            CustomRedisError::ParseError(details) => FlagError::flag_data_parsing(format!(
                "Redis data parsing failed: {}",
                simplify_serde_error(&details)
            )),
            CustomRedisError::Timeout => FlagError::TimeoutError(Some("Redis timeout".to_string())),
            e @ (CustomRedisError::InvalidConfiguration(_) | CustomRedisError::Redis(_)) => {
                FlagError::redis_unavailable(e)
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
                if is_timeout_error(&e) {
                    // Timeouts get their own retryable classification (503) with a type tag.
                    FlagError::TimeoutError(extract_timeout_type(&e).map(|s| s.to_string()))
                } else if is_transient_error(&e) {
                    // Connection resets, serialization failures, and other transient
                    // connection-level Postgres faults are retryable, so surface them as a
                    // 503 rather than treating a DB blip as a hard 500 SDKs won't retry.
                    //
                    // DatabaseUnavailable carries no payload, so log the cause here or the
                    // SQLSTATE is lost — that detail is what distinguishes a connection
                    // blip (08***) from resource exhaustion (53***) during an incident.
                    tracing::warn!(
                        sqlstate = e.as_database_error().and_then(|db| db.code()).as_deref(),
                        "Transient database error, returning 503: {}",
                        e
                    );
                    FlagError::DatabaseUnavailable
                } else {
                    // Genuine internal faults (data corruption, unknown SQLSTATEs) stay 500.
                    FlagError::DatabaseError(e, None)
                }
            }
        }
    }
}

impl From<HyperCacheError> for FlagError {
    fn from(e: HyperCacheError) -> Self {
        match e {
            HyperCacheError::CacheMiss => FlagError::cache_miss(),
            HyperCacheError::Redis(redis_error) => FlagError::from(redis_error),
            HyperCacheError::S3(_) => FlagError::cache_miss(),
            e @ (HyperCacheError::Json(_) | HyperCacheError::Pickle(_)) => {
                FlagError::data_parsing(e)
            }
            HyperCacheError::Timeout(_) => {
                FlagError::TimeoutError(Some("cache_timeout".to_string()))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use tokio::time::{timeout, Duration};

    /// These strings reach customers as the `$feature_flag_reason` event property.
    #[rstest]
    #[case(FlagError::internal(anyhow::anyhow!("boom")), "Internal error: boom")]
    #[case(
        FlagError::flag_data_parsing("bad json"),
        "Failed to parse flag data: bad json"
    )]
    #[case(
        FlagError::data_parsing(anyhow::anyhow!("bad payload")),
        "Failed to parse data"
    )]
    #[case(
        FlagError::batch_evaluation_panicked(),
        "Parallel batch evaluation task panicked"
    )]
    #[case(
        FlagError::redis_unavailable(anyhow::anyhow!("connection refused")),
        "redis unavailable"
    )]
    #[case(FlagError::cache_miss(), "Cache miss - data not found in cache")]
    #[case(FlagError::person_not_found(), "Person not found")]
    fn test_bucketed_error_descriptions_are_stable(
        #[case] error: FlagError,
        #[case] expected: &str,
    ) {
        assert_eq!(error.evaluation_error_description(), expected);
    }

    #[test]
    fn test_is_5xx() {
        // Test 5XX errors
        assert!(FlagError::internal(anyhow::anyhow!("test")).is_5xx());
        assert!(FlagError::DatabaseUnavailable.is_5xx());
        assert!(FlagError::redis_unavailable(anyhow::anyhow!("connection refused")).is_5xx());
        assert!(FlagError::TimeoutError(None).is_5xx());
        assert!(FlagError::batch_evaluation_panicked().is_5xx());
        assert!(FlagError::RayonSemaphoreTimeout(800).is_5xx());
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

        // Cookieless: DateOutOfRange is client-data (4xx); other SaltCache errors are server faults (5xx).
        let salt_cache_cases = [
            (SaltCacheError::DateOutOfRange, false),
            (SaltCacheError::SaltRetrievalFailed, true),
            (SaltCacheError::RedisError("boom".to_string()), true),
        ];
        for (variant, expected_5xx) in salt_cache_cases {
            let err = FlagError::CookielessError(CookielessManagerError::SaltCacheError(variant));
            assert_eq!(err.is_5xx(), expected_5xx, "is_5xx() mismatch for {err:?}");
        }
    }

    #[test]
    fn test_date_out_of_range_is_400() {
        // is_5xx() for this variant is covered by the SaltCacheError table in test_is_5xx.
        let err = FlagError::CookielessError(CookielessManagerError::SaltCacheError(
            SaltCacheError::DateOutOfRange,
        ));
        assert_eq!(err.status_code(), 400);
        assert_eq!(err.error_code(), "cookieless_error");
    }

    #[test]
    fn test_date_out_of_range_response_body() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let err = FlagError::CookielessError(CookielessManagerError::SaltCacheError(
            SaltCacheError::DateOutOfRange,
        ));

        let response = err.into_response();
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);

        let body_bytes = rt
            .block_on(axum::body::to_bytes(response.into_body(), usize::MAX))
            .unwrap();
        let body = String::from_utf8(body_bytes.to_vec()).unwrap();
        assert!(
            body.contains("Invalid sent_at"),
            "body should describe the bad sent_at, got: {body}"
        );
    }

    fn response_body(error: FlagError) -> (StatusCode, String) {
        let rt = tokio::runtime::Runtime::new().unwrap();
        let response = error.into_response();
        let status = response.status();
        let bytes = rt
            .block_on(axum::body::to_bytes(response.into_body(), usize::MAX))
            .unwrap();
        (status, String::from_utf8(bytes.to_vec()).unwrap())
    }

    /// Every bucketed code renders one of three bodies. A corrupt flag definition
    /// fails each retry, so it gets guidance the other two cannot give; the rest
    /// share a body, which is the wording that replaced their per-variant text.
    #[rstest]
    #[case(
        FlagError::flag_data_parsing("bad json"),
        StatusCode::INTERNAL_SERVER_ERROR,
        "check your flag definitions"
    )]
    #[case(
        FlagError::data_parsing(anyhow::anyhow!("bad payload")),
        StatusCode::INTERNAL_SERVER_ERROR,
        "An internal server error occurred"
    )]
    #[case(
        FlagError::batch_evaluation_panicked(),
        StatusCode::INTERNAL_SERVER_ERROR,
        "An internal server error occurred"
    )]
    #[case(
        FlagError::internal(anyhow::anyhow!("boom")),
        StatusCode::INTERNAL_SERVER_ERROR,
        "An internal server error occurred"
    )]
    #[case(
        FlagError::redis_unavailable(anyhow::anyhow!("connection refused")),
        StatusCode::SERVICE_UNAVAILABLE,
        "A service dependency is temporarily unavailable"
    )]
    #[case(
        FlagError::cache_miss(),
        StatusCode::SERVICE_UNAVAILABLE,
        "A service dependency is temporarily unavailable"
    )]
    #[case(
        FlagError::person_not_found(),
        StatusCode::SERVICE_UNAVAILABLE,
        "A service dependency is temporarily unavailable"
    )]
    fn test_bucketed_response_bodies(
        #[case] error: FlagError,
        #[case] expected_status: StatusCode,
        #[case] expected_body: &str,
    ) {
        let (status, body) = response_body(error);
        assert_eq!(status, expected_status);
        assert!(
            body.contains(expected_body),
            "expected body to contain {expected_body:?}, got: {body}"
        );
    }

    /// `IntoResponse` picks the log level by comparing `code`, which the compiler
    /// cannot check. A drift here would silently bury a Redis outage at warn.
    #[rstest]
    #[case(FlagError::redis_unavailable(anyhow::anyhow!("refused")), "ERROR")]
    #[case(FlagError::cache_miss(), "ERROR")]
    #[case(FlagError::person_not_found(), "WARN")]
    #[case(FlagError::internal(anyhow::anyhow!("boom")), "ERROR")]
    fn test_bucketed_log_levels(#[case] error: FlagError, #[case] expected_level: &str) {
        #[derive(Clone, Default)]
        struct Capture(std::sync::Arc<std::sync::Mutex<Vec<u8>>>);

        impl std::io::Write for Capture {
            fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
                self.0.lock().unwrap().extend_from_slice(buf);
                Ok(buf.len())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }

        impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for Capture {
            type Writer = Self;
            fn make_writer(&'a self) -> Self::Writer {
                self.clone()
            }
        }

        let writer = Capture::default();
        let subscriber = tracing_subscriber::fmt()
            .json()
            .with_writer(writer.clone())
            .with_max_level(tracing::Level::INFO)
            .finish();
        tracing::subscriber::with_default(subscriber, || {
            drop(error.into_response());
        });

        let logs = String::from_utf8(writer.0.lock().unwrap().clone()).unwrap();
        assert!(
            logs.contains(&format!("\"level\":\"{expected_level}\"")),
            "expected a {expected_level} line, got: {logs}"
        );
    }

    #[test]
    fn test_remote_config_decrypt_failed_response_is_json() {
        // The remote_config response body must be JSON on every status code, because SDKs call
        // res.json() on it unconditionally, so a plain-text 500 would crash them client-side.
        let rt = tokio::runtime::Runtime::new().unwrap();
        let err = FlagError::RemoteConfigDecryptFailed("failed to decrypt payload".to_string());

        let response = err.into_response();
        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(
            response
                .headers()
                .get("content-type")
                .and_then(|v| v.to_str().ok()),
            Some("application/json")
        );

        let body_bytes = rt
            .block_on(axum::body::to_bytes(response.into_body(), usize::MAX))
            .unwrap();
        let body: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap();
        assert_eq!(body["code"], "remote_config_decrypt_failed");
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
    fn test_direct_sqlx_transient_conversion_is_503() {
        // Transient/connection-level failures propagated via `?` must map to the retryable
        // DatabaseUnavailable (503), not DatabaseError (500), so SDKs retry on a DB blip.
        let pool_closed: FlagError = sqlx::Error::PoolClosed.into();
        assert!(matches!(pool_closed, FlagError::DatabaseUnavailable));
        assert_eq!(pool_closed.status_code(), 503);

        let io_reset: FlagError = sqlx::Error::Io(std::io::Error::new(
            std::io::ErrorKind::ConnectionReset,
            "connection reset by peer",
        ))
        .into();
        assert!(matches!(io_reset, FlagError::DatabaseUnavailable));
        assert_eq!(io_reset.status_code(), 503);

        let tls_error: FlagError =
            sqlx::Error::Tls(Box::new(std::io::Error::other("TLS handshake failed"))).into();
        assert!(matches!(tls_error, FlagError::DatabaseUnavailable));
        assert_eq!(tls_error.status_code(), 503);
    }

    #[test]
    fn test_direct_sqlx_internal_fault_stays_500() {
        // Genuine internal faults (schema/config problems) are not transient and must
        // remain DatabaseError (500) so they are not masked as retryable.
        let column_error: FlagError = sqlx::Error::ColumnNotFound("missing".to_string()).into();
        assert!(matches!(column_error, FlagError::DatabaseError(_, _)));
        assert_eq!(column_error.status_code(), 500);

        let config_error: FlagError =
            sqlx::Error::Configuration("invalid connection string".into()).into();
        assert!(matches!(config_error, FlagError::DatabaseError(_, _)));
        assert_eq!(config_error.status_code(), 500);
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
            FlagError::internal(anyhow::anyhow!("test")),
            FlagError::RequestDecodingError("test".to_string()),
            serde_json::from_str::<String>("invalid json")
                .unwrap_err()
                .into(), // RequestParsingError
            FlagError::MissingDistinctId,
            FlagError::PayloadTooLarge {
                decompressed: 5_000_000,
                limit: 4 * 1024 * 1024,
            },
            FlagError::NoTokenError,
            FlagError::TokenValidationError,
            FlagError::PersonalApiKeyInvalid,
            FlagError::PersonalApiKeyInsufficientScopes,
            FlagError::SecretApiTokenInvalid,
            FlagError::NoAuthenticationProvided,
            FlagError::RowNotFound,
            FlagError::flag_data_parsing("test parse error"),
            FlagError::redis_unavailable(anyhow::anyhow!("connection refused")),
            FlagError::DatabaseUnavailable,
            FlagError::DatabaseError(sqlx::Error::RowNotFound, Some("test context".to_string())),
            FlagError::TimeoutError(None),
            FlagError::DependencyNotFound(DependencyType::Flag, 1),
            FlagError::DependencyCycle(DependencyType::Cohort, 2),
            FlagError::CohortFiltersParsingError,
            FlagError::person_not_found(),
            FlagError::cache_miss(),
            FlagError::data_parsing(anyhow::anyhow!("bad payload")),
            FlagError::batch_evaluation_panicked(),
            FlagError::HashKeyOverrideError,
            FlagError::RayonSemaphoreTimeout(800),
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
        assert_eq!(
            FlagError::PayloadTooLarge {
                decompressed: 5_000_000,
                limit: 4 * 1024 * 1024
            }
            .status_code(),
            413
        );

        // 5xx errors (server errors)
        assert_eq!(FlagError::internal(anyhow::anyhow!("")).status_code(), 500);
        assert_eq!(FlagError::DatabaseUnavailable.status_code(), 503);
        assert_eq!(
            FlagError::redis_unavailable(anyhow::anyhow!("connection refused")).status_code(),
            503
        );
        assert_eq!(FlagError::TimeoutError(None).status_code(), 503);
        assert_eq!(
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable).status_code(),
            503
        );
        assert_eq!(FlagError::RowNotFound.status_code(), 500);
        // Cache miss errors are now 503 (transient)
        assert_eq!(FlagError::person_not_found().status_code(), 503);
        // Semaphore timeout is 504 (gateway timeout for ingress retry)
        assert_eq!(FlagError::RayonSemaphoreTimeout(800).status_code(), 504);
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
            FlagError::internal(anyhow::anyhow!("")),
            FlagError::RowNotFound,
            FlagError::CohortFiltersParsingError,
            FlagError::data_parsing(anyhow::anyhow!("bad payload")),
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
            FlagError::internal(anyhow::anyhow!("test")),
            FlagError::DatabaseError(sqlx::Error::RowNotFound, None),
            FlagError::RowNotFound,
            FlagError::DependencyNotFound(DependencyType::Flag, 1),
            FlagError::CohortFiltersParsingError,
            FlagError::DependencyCycle(DependencyType::Cohort, 2),
            FlagError::data_parsing(anyhow::anyhow!("bad payload")),
            FlagError::batch_evaluation_panicked(),
            FlagError::HashKeyOverrideError,
            FlagError::RayonSemaphoreTimeout(800),
            FlagError::flag_data_parsing("test"),
            FlagError::redis_unavailable(anyhow::anyhow!("connection refused")),
            FlagError::DatabaseUnavailable,
            FlagError::TimeoutError(None),
            FlagError::cache_miss(),
            FlagError::person_not_found(),
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
    fn test_is_token_not_found() {
        // These errors mean the token definitively doesn't map to a team
        assert!(FlagError::TokenValidationError.is_token_not_found());
        assert!(FlagError::RowNotFound.is_token_not_found());

        // Transient infrastructure errors should NOT be treated as "not found"
        assert!(!FlagError::cache_miss().is_token_not_found());
        assert!(
            !FlagError::redis_unavailable(anyhow::anyhow!("connection refused"))
                .is_token_not_found()
        );
        assert!(!FlagError::DatabaseUnavailable.is_token_not_found());
        assert!(!FlagError::TimeoutError(None).is_token_not_found());
        assert!(!FlagError::TimeoutError(Some("pool_timeout".to_string())).is_token_not_found());
        assert!(!FlagError::DatabaseError(sqlx::Error::PoolTimedOut, None).is_token_not_found());
        assert!(!FlagError::internal(anyhow::anyhow!("serialization failed")).is_token_not_found());
        assert!(!FlagError::data_parsing(anyhow::anyhow!("bad payload")).is_token_not_found());
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
            FlagError::redis_unavailable(anyhow::anyhow!("connection refused")).error_code(),
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
            FlagError::internal(anyhow::anyhow!("test")),
            FlagError::RequestDecodingError("test".to_string()),
            serde_json::from_str::<String>("invalid json")
                .unwrap_err()
                .into(), // RequestParsingError
            FlagError::MissingDistinctId,
            FlagError::PayloadTooLarge {
                decompressed: 5_000_000,
                limit: 4 * 1024 * 1024,
            },
            FlagError::NoTokenError,
            FlagError::TokenValidationError,
            FlagError::PersonalApiKeyInvalid,
            FlagError::PersonalApiKeyInsufficientScopes,
            FlagError::SecretApiTokenInvalid,
            FlagError::NoAuthenticationProvided,
            FlagError::RowNotFound,
            FlagError::flag_data_parsing("test parse error"),
            FlagError::redis_unavailable(anyhow::anyhow!("connection refused")),
            FlagError::DatabaseUnavailable,
            FlagError::DatabaseError(sqlx::Error::RowNotFound, Some("test context".to_string())),
            FlagError::TimeoutError(None),
            FlagError::DependencyNotFound(DependencyType::Flag, 1),
            FlagError::DependencyCycle(DependencyType::Cohort, 2),
            FlagError::CohortFiltersParsingError,
            FlagError::person_not_found(),
            FlagError::cache_miss(),
            FlagError::data_parsing(anyhow::anyhow!("bad payload")),
            FlagError::batch_evaluation_panicked(),
            FlagError::HashKeyOverrideError,
            FlagError::RayonSemaphoreTimeout(800),
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
