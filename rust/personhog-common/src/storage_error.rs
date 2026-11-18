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

impl StorageError {
    /// The `error_type` metric label.
    pub fn error_type(&self) -> &'static str {
        match self {
            Self::Connection(_) => "connection",
            Self::Query(_) => "query",
            Self::Timeout { kind, .. } => kind.as_str(),
            Self::PoolExhausted => "pool_exhausted",
            Self::NotFound(_) => "not_found",
            Self::FailedPrecondition(_) => "failed_precondition",
        }
    }
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

    pub(crate) fn as_str(self) -> &'static str {
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

#[cfg(test)]
mod tests {
    use std::borrow::Cow;
    use std::fmt;

    use rstest::rstest;

    use super::*;

    #[derive(Debug)]
    struct FakePgError(&'static str);

    impl fmt::Display for FakePgError {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "fake database error ({})", self.0)
        }
    }

    impl std::error::Error for FakePgError {}

    impl sqlx::error::DatabaseError for FakePgError {
        fn message(&self) -> &str {
            "fake database error"
        }

        fn code(&self) -> Option<Cow<'_, str>> {
            Some(Cow::Borrowed(self.0))
        }

        fn as_error(&self) -> &(dyn std::error::Error + Send + Sync + 'static) {
            self
        }

        fn as_error_mut(&mut self) -> &mut (dyn std::error::Error + Send + Sync + 'static) {
            self
        }

        fn into_error(self: Box<Self>) -> Box<dyn std::error::Error + Send + Sync + 'static> {
            self
        }

        fn kind(&self) -> sqlx::error::ErrorKind {
            sqlx::error::ErrorKind::Other
        }
    }

    #[rstest]
    #[case::statement_timeout("57014", "statement_timeout")]
    #[case::lock_timeout("55P03", "lock_timeout")]
    #[case::unique_violation("23505", "query")]
    #[case::deadlock("40P01", "query")]
    fn database_error_is_classified_by_sqlstate(
        #[case] sqlstate: &'static str,
        #[case] expected_error_type: &str,
    ) {
        let err = StorageError::from(sqlx::Error::Database(Box::new(FakePgError(sqlstate))));

        assert_eq!(err.error_type(), expected_error_type);
    }
}
