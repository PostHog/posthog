//! Shared storage-error classification for personhog services backed by the
//! persons Postgres. The variants map 1:1 onto the gRPC status codes the
//! services surface, so the classification lives here rather than per
//! service.

use thiserror::Error;

#[derive(Error, Debug, Clone)]
pub enum StorageError {
    /// Connection-level errors (network, TLS, authentication)
    #[error("Database connection error: {0}")]
    Connection(String),

    /// Query execution errors (SQL errors, constraint violations)
    #[error("Database query error: {0}")]
    Query(String),

    /// Postgres cancelled a statement because a timeout fired. That
    /// statement's transaction rolled back.
    #[error("Database {}: {message}", .kind.as_str())]
    Timeout { kind: TimeoutKind, message: String },

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

#[derive(Clone, Copy, Debug)]
pub enum TimeoutKind {
    Statement,
    Lock,
}

impl TimeoutKind {
    /// SQLSTATE 57014 also covers a `pg_cancel_backend` call, which this
    /// reports as a statement timeout.
    fn from_sqlstate(code: Option<&str>) -> Option<Self> {
        match code {
            Some("57014") => Some(Self::Statement),
            Some("55P03") => Some(Self::Lock),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Statement => "statement_timeout",
            Self::Lock => "lock_timeout",
        }
    }
}

impl From<sqlx::Error> for StorageError {
    fn from(err: sqlx::Error) -> Self {
        match &err {
            sqlx::Error::PoolTimedOut | sqlx::Error::PoolClosed => StorageError::PoolExhausted,

            sqlx::Error::Io(_) | sqlx::Error::Tls(_) => StorageError::Connection(err.to_string()),

            sqlx::Error::Database(db) => match TimeoutKind::from_sqlstate(db.code().as_deref()) {
                Some(kind) => StorageError::Timeout {
                    kind,
                    message: err.to_string(),
                },
                None => StorageError::Query(err.to_string()),
            },

            _ => StorageError::Query(err.to_string()),
        }
    }
}

pub type StorageResult<T> = Result<T, StorageError>;
