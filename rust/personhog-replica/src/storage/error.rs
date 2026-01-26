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
}

impl Clone for StorageError {
    fn clone(&self) -> Self {
        match self {
            Self::Connection(msg) => Self::Connection(msg.clone()),
            Self::Query(msg) => Self::Query(msg.clone()),
            Self::PoolExhausted => Self::PoolExhausted,
        }
    }
}

pub type StorageResult<T> = Result<T, StorageError>;
