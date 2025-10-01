use std::{sync::Arc, time::Duration};

use anyhow::Result;
use async_trait::async_trait;
use sqlx::{
    pool::PoolConnection,
    postgres::{PgPool, PgPoolOptions, PgRow},
    Error as SqlxError, Postgres,
};
use thiserror::Error;
use tokio::time::timeout;

const DATABASE_TIMEOUT_MILLISECS: u64 = 1000;

#[derive(Error, Debug)]
pub enum CustomDatabaseError {
    #[error("Pg error: {0}")]
    Other(#[from] sqlx::Error),

    #[error("Timeout error")]
    Timeout(#[from] tokio::time::error::Elapsed),
}

pub type PostgresReader = Arc<dyn Client + Send + Sync>;
pub type PostgresWriter = Arc<dyn Client + Send + Sync>;

/// A simple db wrapper
/// Supports running any arbitrary query with a timeout.
/// TODO: Make sqlx prepared statements work with pgbouncer, potentially by setting pooling mode to session.
#[async_trait]
pub trait Client {
    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError>;
    async fn run_query(
        &self,
        query: String,
        parameters: Vec<String>,
        timeout_ms: Option<u64>,
    ) -> Result<Vec<PgRow>, CustomDatabaseError>;

    fn get_pool_stats(&self) -> Option<PoolStats>;
}

#[derive(Debug, Clone)]
pub struct PoolStats {
    pub size: u32,
    pub num_idle: usize,
}

/// Configuration for database connection pool
/// Each service should provide its own configuration based on its needs
#[derive(Debug, Clone)]
pub struct PoolConfig {
    pub max_connections: u32,
    pub acquire_timeout: Duration,
    pub idle_timeout: Option<Duration>,
    pub max_lifetime: Option<Duration>,
    pub test_before_acquire: bool,
}

impl Default for PoolConfig {
    /// Provides sensible production defaults
    /// Services can override these with their own environment-based configs
    fn default() -> Self {
        Self {
            max_connections: 10,
            acquire_timeout: Duration::from_secs(10),
            idle_timeout: Some(Duration::from_secs(300)), // Close idle connections after 5 minutes
            max_lifetime: Some(Duration::from_secs(1800)), // Force refresh connections after 30 minutes
            test_before_acquire: true,                     // Test connection health before use
        }
    }
}

/// Legacy function for backward compatibility - uses default production settings
/// New services should use get_pool_with_config() with their own PoolConfig
pub async fn get_pool(url: &str, max_connections: u32) -> Result<PgPool, sqlx::Error> {
    let config = PoolConfig {
        max_connections,
        ..Default::default()
    };
    get_pool_with_config(url, config).await
}

/// Legacy function for backward compatibility - uses default production settings except for timeout
/// New services should use get_pool_with_config() with their own PoolConfig
pub async fn get_pool_with_timeout(
    url: &str,
    max_connections: u32,
    acquire_timeout: Duration,
) -> Result<PgPool, sqlx::Error> {
    let config = PoolConfig {
        max_connections,
        acquire_timeout,
        ..Default::default()
    };
    get_pool_with_config(url, config).await
}

/// Creates a database pool with the provided configuration
/// This is the recommended function for services to use
pub async fn get_pool_with_config(url: &str, config: PoolConfig) -> Result<PgPool, sqlx::Error> {
    let mut options = PgPoolOptions::new()
        .max_connections(config.max_connections)
        .acquire_timeout(config.acquire_timeout)
        .test_before_acquire(config.test_before_acquire);

    if let Some(idle_timeout) = config.idle_timeout {
        options = options.idle_timeout(idle_timeout);
    }

    if let Some(max_lifetime) = config.max_lifetime {
        options = options.max_lifetime(max_lifetime);
    }

    options.connect(url).await
}

#[async_trait]
impl Client for PgPool {
    fn get_pool_stats(&self) -> Option<PoolStats> {
        Some(PoolStats {
            size: self.size(),
            num_idle: self.num_idle(),
        })
    }

    async fn run_query(
        &self,
        query: String,
        parameters: Vec<String>,
        timeout_ms: Option<u64>,
    ) -> Result<Vec<PgRow>, CustomDatabaseError> {
        let built_query = sqlx::query(&query);
        let built_query = parameters
            .iter()
            .fold(built_query, |acc, param| acc.bind(param));
        let query_results = built_query.fetch_all(self);

        let timeout_ms = match timeout_ms {
            Some(ms) => ms,
            None => DATABASE_TIMEOUT_MILLISECS,
        };

        let fut = timeout(Duration::from_millis(timeout_ms), query_results).await?;

        Ok(fut?)
    }

    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        Ok(self.acquire().await?)
    }
}

/// Determines if a sqlx::Error represents a foreign key constraint violation
pub fn is_foreign_key_constraint_error(error: &SqlxError) -> bool {
    match error {
        SqlxError::Database(db_error) => {
            // Class 23 — Integrity Constraint Violation; 23503 = foreign_key_violation
            // See: https://www.postgresql.org/docs/current/errcodes-appendix.html
            if let Some(code) = db_error.code() {
                code.as_ref() == "23503"
            } else {
                let msg = db_error.message().to_lowercase();
                msg.contains("violates foreign key constraint")
                    || msg.contains("foreign key constraint")
            }
        }
        _ => false,
    }
}

/// Determines if a sqlx::Error represents a transient failure that should be retried
pub fn is_transient_error(error: &SqlxError) -> bool {
    match error {
        // Connection/pool issues: usually transient.
        SqlxError::Io(_)
        | SqlxError::PoolTimedOut
        | SqlxError::PoolClosed
        // TLS/handshake can be transient (network/cert rollover).
        | SqlxError::Tls(_) => true,

        // Database-specific errors: prefer SQLSTATE when available.
        SqlxError::Database(db_error) => {
            if let Some(code) = db_error.code() {
                let code = code.as_ref();

                // See: PostgreSQL SQLSTATE appendix
                // 08***  Connection Exception
                // 53***  Insufficient Resources
                // 57***  Operator Intervention
                // 58***  System Error (often transient)
                // 40001  Serialization Failure
                // 40003  Statement Completion Unknown (retry if idempotent)
                // 40P01  Deadlock Detected
                code.starts_with("08")
                    || code.starts_with("53")
                    || code.starts_with("57")
                    || code.starts_with("58")
                    || code == "40001"
                    || code == "40003"
                    || code == "40P01"
            } else {
                // Last resort: message heuristics (less reliable than SQLSTATE).
                let msg = db_error.message().to_lowercase();
                msg.contains("connection")
                    || msg.contains("timeout")
                    || msg.contains("timed out")
                    || msg.contains("temporary")
                    || msg.contains("deadlock")
                    || msg.contains("serialization")
                    || msg.contains("disk full")
                    || msg.contains("canceling statement due to")
                    || msg.contains("terminating connection due to")
                    || msg.contains("ssl")
                    || msg.contains("tls")
            }
        }

        // Protocol glitches may be transient.
        SqlxError::Protocol(msg) => {
            let m = msg.to_lowercase();
            m.contains("connection") || m.contains("timeout") || m.contains("ssl") || m.contains("tls")
        }

        // Default: assume non-transient since we're not sure about the error type.
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sqlx::Error as SqlxError;

    #[test]
    fn test_is_transient_error_connection_errors() {
        // Test that database connection errors trigger retries
        let pool_timeout_error = SqlxError::PoolTimedOut;
        assert!(is_transient_error(&pool_timeout_error));

        let pool_closed_error = SqlxError::PoolClosed;
        assert!(is_transient_error(&pool_closed_error));

        let io_error = SqlxError::Io(std::io::Error::new(
            std::io::ErrorKind::ConnectionRefused,
            "connection refused",
        ));
        assert!(is_transient_error(&io_error));

        // Test TLS errors are considered transient
        let tls_error = SqlxError::Tls(Box::new(std::io::Error::other("TLS handshake failed")));
        assert!(is_transient_error(&tls_error));
    }

    #[test]
    fn test_is_transient_error_protocol_errors() {
        // Test Protocol errors with connection issues
        let protocol_connection_error = SqlxError::Protocol("connection lost".to_string());
        assert!(is_transient_error(&protocol_connection_error));

        let protocol_timeout_error = SqlxError::Protocol("operation timeout".to_string());
        assert!(is_transient_error(&protocol_timeout_error));

        // Test that non-connection protocol errors don't trigger retries
        let protocol_other_error = SqlxError::Protocol("invalid protocol version".to_string());
        assert!(!is_transient_error(&protocol_other_error));
    }

    #[test]
    fn test_is_transient_error_non_transient_errors() {
        // Test that configuration errors don't trigger retries
        let config_error =
            SqlxError::Configuration(Box::new(std::io::Error::other("invalid connection string")));
        assert!(!is_transient_error(&config_error));

        let column_error = SqlxError::ColumnNotFound("missing_column".to_string());
        assert!(!is_transient_error(&column_error));

        let row_not_found = SqlxError::RowNotFound;
        assert!(!is_transient_error(&row_not_found));

        let worker_crashed = SqlxError::WorkerCrashed;
        assert!(!is_transient_error(&worker_crashed));
    }

    #[test]
    fn test_is_foreign_key_constraint_error_non_database_errors() {
        // Test that non-database errors don't trigger foreign key detection
        let config_error =
            SqlxError::Configuration(Box::new(std::io::Error::other("invalid connection string")));
        assert!(!is_foreign_key_constraint_error(&config_error));

        let column_error = SqlxError::ColumnNotFound("missing_column".to_string());
        assert!(!is_foreign_key_constraint_error(&column_error));

        let row_not_found = SqlxError::RowNotFound;
        assert!(!is_foreign_key_constraint_error(&row_not_found));
    }

    #[test]
    fn test_is_foreign_key_constraint_error_protocol_errors() {
        // Test that protocol errors don't trigger foreign key detection
        let protocol_error = SqlxError::Protocol("some protocol error".to_string());
        assert!(!is_foreign_key_constraint_error(&protocol_error));
    }

    // Mock database error implementation for comprehensive testing
    use sqlx::error::{DatabaseError, ErrorKind};
    use std::{borrow::Cow, error::Error as StdError, fmt};

    #[derive(Debug)]
    struct MockDbError {
        msg: &'static str,
        code: Option<&'static str>,
        kind: ErrorKind,
    }

    impl fmt::Display for MockDbError {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.write_str(self.msg)
        }
    }

    impl StdError for MockDbError {}

    impl DatabaseError for MockDbError {
        fn message(&self) -> &str {
            self.msg
        }
        fn kind(&self) -> ErrorKind {
            // We can't clone ErrorKind, so we'll return a reasonable default
            match self.kind {
                ErrorKind::UniqueViolation => ErrorKind::UniqueViolation,
                ErrorKind::ForeignKeyViolation => ErrorKind::ForeignKeyViolation,
                ErrorKind::NotNullViolation => ErrorKind::NotNullViolation,
                ErrorKind::CheckViolation => ErrorKind::CheckViolation,
                _ => ErrorKind::Other,
            }
        }
        // Optionally surface a SQLSTATE
        fn code(&self) -> Option<Cow<'_, str>> {
            self.code.map(Cow::from)
        }

        fn as_error(&self) -> &(dyn StdError + Send + Sync + 'static) {
            self
        }

        fn as_error_mut(&mut self) -> &mut (dyn StdError + Send + Sync + 'static) {
            self
        }

        fn into_error(self: Box<Self>) -> Box<dyn StdError + Send + Sync + 'static> {
            self
        }
    }

    // Convenience: build a sqlx::Error::Database
    fn db_err(msg: &'static str, code: Option<&'static str>, kind: ErrorKind) -> SqlxError {
        SqlxError::from(MockDbError { msg, code, kind })
    }

    #[test]
    fn test_foreign_key_constraint_error_with_sqlstate() {
        // Test FK constraint violation with SQLSTATE 23503
        let fk_error = db_err(
            "insert violates foreign key constraint \"fk_constraint\"",
            Some("23503"),
            ErrorKind::ForeignKeyViolation,
        );
        assert!(is_foreign_key_constraint_error(&fk_error));

        // Test non-FK constraint violations don't match
        let unique_error = db_err(
            "duplicate key value violates unique constraint",
            Some("23505"),
            ErrorKind::UniqueViolation,
        );
        assert!(!is_foreign_key_constraint_error(&unique_error));
    }

    #[test]
    fn test_foreign_key_constraint_error_message_fallback() {
        // Test message fallback when no SQLSTATE code is available
        let fk_error_no_code = db_err(
            "insert violates foreign key constraint \"user_fk\"",
            None,
            ErrorKind::ForeignKeyViolation,
        );
        assert!(is_foreign_key_constraint_error(&fk_error_no_code));

        // Test shorter message pattern
        let fk_error_short = db_err(
            "foreign key constraint violation",
            None,
            ErrorKind::ForeignKeyViolation,
        );
        assert!(is_foreign_key_constraint_error(&fk_error_short));

        // Test case insensitivity
        let fk_error_caps = db_err(
            "INSERT VIOLATES FOREIGN KEY CONSTRAINT",
            None,
            ErrorKind::ForeignKeyViolation,
        );
        assert!(is_foreign_key_constraint_error(&fk_error_caps));

        // Test non-FK messages don't match
        let other_error = db_err("some other database error", None, ErrorKind::Other);
        assert!(!is_foreign_key_constraint_error(&other_error));
    }

    #[test]
    fn test_transient_error_sqlstate_classes() {
        // 08*** Connection Exception
        let conn_err = db_err(
            "connection dropped unexpectedly",
            Some("08006"),
            ErrorKind::Other,
        );
        assert!(is_transient_error(&conn_err));

        // 53*** Insufficient Resources
        let disk_full_err = db_err(
            "could not extend file: No space left on device",
            Some("53100"),
            ErrorKind::Other,
        );
        assert!(is_transient_error(&disk_full_err));

        // 57*** Operator Intervention
        let cancel_err = db_err(
            "canceling statement due to statement timeout",
            Some("57014"),
            ErrorKind::Other,
        );
        assert!(is_transient_error(&cancel_err));

        // 58*** System Error
        let sys_err = db_err(
            "could not read block: Input/output error",
            Some("58030"),
            ErrorKind::Other,
        );
        assert!(is_transient_error(&sys_err));

        // 40001 Serialization Failure
        let serialization_err = db_err(
            "could not serialize access due to concurrent update",
            Some("40001"),
            ErrorKind::Other,
        );
        assert!(is_transient_error(&serialization_err));

        // 40003 Statement Completion Unknown
        let completion_unknown = db_err(
            "statement completion unknown",
            Some("40003"),
            ErrorKind::Other,
        );
        assert!(is_transient_error(&completion_unknown));

        // 40P01 Deadlock Detected
        let deadlock_err = db_err("deadlock detected", Some("40P01"), ErrorKind::Other);
        assert!(is_transient_error(&deadlock_err));
    }

    #[test]
    fn test_transient_error_non_transient_sqlstates() {
        // 23*** Integrity Constraint Violations (generally permanent)
        let unique_violation = db_err(
            "duplicate key value violates unique constraint",
            Some("23505"),
            ErrorKind::UniqueViolation,
        );
        assert!(!is_transient_error(&unique_violation));

        // 42*** Syntax Error or Access Rule Violation (permanent)
        let syntax_error = db_err(
            "syntax error at or near \"SELECT\"",
            Some("42601"),
            ErrorKind::Other,
        );
        assert!(!is_transient_error(&syntax_error));

        // 22*** Data Exception (usually permanent)
        let data_exception = db_err(
            "invalid input syntax for type integer",
            Some("22P02"),
            ErrorKind::Other,
        );
        assert!(!is_transient_error(&data_exception));
    }

    #[test]
    fn test_transient_error_message_fallback() {
        // Test message heuristics when no SQLSTATE is available
        let connection_msg_err = db_err("connection to server was lost", None, ErrorKind::Other);
        assert!(is_transient_error(&connection_msg_err));

        let timeout_msg_err = db_err("operation timed out", None, ErrorKind::Other);
        assert!(is_transient_error(&timeout_msg_err));

        let ssl_msg_err = db_err(
            "SSL connection has been closed unexpectedly",
            None,
            ErrorKind::Other,
        );
        assert!(is_transient_error(&ssl_msg_err));

        // Test non-transient message
        let permanent_msg_err = db_err("column does not exist", None, ErrorKind::Other);
        assert!(!is_transient_error(&permanent_msg_err));

        // Test that memory pressure errors are NOT retried to avoid amplifying load
        let memory_err = db_err("out of memory", None, ErrorKind::Other);
        assert!(!is_transient_error(&memory_err));
    }
}
