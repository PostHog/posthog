use common_database::CustomDatabaseError;
use common_redis::CustomRedisError;
use sqlx::Error as SqlxError;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ModelError {
    #[error("Failed to parse redis cache data")]
    RedisDataParsingError,
    #[error("Failed to update redis cache")]
    CacheUpdateError,
    #[error("Token validation error")]
    TokenValidationError,
    #[error("Row not found")]
    RowNotFound,
    #[error("Redis unavailable")]
    RedisUnavailable,
    #[error("Database unavailable")]
    DatabaseUnavailable,
    #[error("Timeout error")]
    TimeoutError,
}

impl From<CustomRedisError> for ModelError {
    fn from(e: CustomRedisError) -> Self {
        match e {
            CustomRedisError::NotFound => ModelError::TokenValidationError,
            CustomRedisError::ParseError(e) => {
                tracing::error!("failed to fetch data from redis: {}", e);
                ModelError::RedisDataParsingError
            }
            CustomRedisError::Timeout => ModelError::TimeoutError,
            CustomRedisError::Other(e) => {
                tracing::error!("Unknown redis error: {}", e);
                ModelError::RedisUnavailable
            }
        }
    }
}

impl From<CustomDatabaseError> for ModelError {
    fn from(e: CustomDatabaseError) -> Self {
        match e {
            CustomDatabaseError::Other(_) => {
                tracing::error!("failed to get connection: {}", e);
                ModelError::DatabaseUnavailable
            }
            CustomDatabaseError::Timeout(_) => ModelError::TimeoutError,
        }
    }
}

impl From<SqlxError> for ModelError {
    fn from(e: SqlxError) -> Self {
        match e {
            SqlxError::RowNotFound => ModelError::RowNotFound,
            _ => ModelError::DatabaseUnavailable,
        }
    }
}
