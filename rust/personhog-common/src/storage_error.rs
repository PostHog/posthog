//! Shared storage-error classification for personhog services backed by the
//! persons Postgres. The variants map 1:1 onto the gRPC status codes the
//! services surface, so the classification lives here rather than per
//! service.

use thiserror::Error;

#[derive(Error, Debug)]
pub enum StorageError {
    /// Connection-level errors (network, TLS, authentication)
    #[error("Database connection error: {0}")]
    Connection(String),

    /// Query execution errors (SQL errors, constraint violations)
    #[error("Database query error: {0}")]
    Query(String),

    /// Connection pool exhausted or closed
    #[error("Database pool exhausted")]
    PoolExhausted,

    /// Resource not found (e.g. person, distinct_id)
    #[error("Not found: {0}")]
    NotFound(String),

    /// Operation precondition violated (e.g. concurrent modification)
    #[error("Failed precondition: {0}")]
    FailedPrecondition(String),
}

impl Clone for StorageError {
    fn clone(&self) -> Self {
        match self {
            Self::Connection(msg) => Self::Connection(msg.clone()),
            Self::Query(msg) => Self::Query(msg.clone()),
            Self::PoolExhausted => Self::PoolExhausted,
            Self::NotFound(msg) => Self::NotFound(msg.clone()),
            Self::FailedPrecondition(msg) => Self::FailedPrecondition(msg.clone()),
        }
    }
}

impl From<sqlx::Error> for StorageError {
    fn from(err: sqlx::Error) -> Self {
        match &err {
            sqlx::Error::PoolTimedOut | sqlx::Error::PoolClosed => StorageError::PoolExhausted,

            sqlx::Error::Io(_) | sqlx::Error::Tls(_) => StorageError::Connection(err.to_string()),

            _ => StorageError::Query(err.to_string()),
        }
    }
}

pub type StorageResult<T> = Result<T, StorageError>;
