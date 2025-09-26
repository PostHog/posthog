use std::{sync::Arc, time::Duration};

use anyhow::Result;
use async_trait::async_trait;
use sqlx::{
    pool::PoolConnection,
    postgres::{PgPool, PgPoolOptions},
    Error as SqlxError, Postgres,
};
use thiserror::Error;

// Default database timeouts - optimized for production low-latency flag evaluation
pub const DEFAULT_TIMEOUTS: DatabaseTimeouts = DatabaseTimeouts {
    statement_timeout: Duration::from_millis(300), // Aggressive for fast flag evaluation
    lock_timeout: Duration::from_millis(100),      // Avoid blocking on locks
    acquire_timeout: Duration::from_millis(200),   // Fail fast under load
    idle_timeout: Duration::from_secs(300),        // Close idle connections after 5 minutes
    max_lifetime: Duration::from_secs(1800),       // Force refresh every 30 minutes
    idle_in_transaction_session_timeout: Duration::from_secs(15), // Kill leaked transactions
};

#[derive(Error, Debug)]
pub enum CustomDatabaseError {
    #[error("Pg error: {0}")]
    Other(#[from] sqlx::Error),

    #[error("Client timeout error")]
    Timeout(#[from] tokio::time::error::Elapsed),
}

pub type PostgresReader = Arc<dyn Client + Send + Sync>;
pub type PostgresWriter = Arc<dyn Client + Send + Sync>;

/// A simple db wrapper
/// Supports running any arbitrary query with a timeout.
///
/// ## Timeout Strategy
/// - Session defaults optimized for fast flag evaluation reads (300ms statement, 100ms lock)
/// - Use `begin_write_transaction()` for writes that need longer timeouts (2s statement, 500ms lock)
/// - Pool acquire timeout is aggressive (200ms) for fail-fast behavior under load
///
/// TODO: Make sqlx prepared statements work with pgbouncer, potentially by setting pooling mode to session.
#[async_trait]
pub trait Client {
    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError>;

    fn get_pool_stats(&self) -> Option<PoolStats>;
}

#[derive(Debug, Clone)]
pub struct PoolStats {
    pub size: u32,
    pub num_idle: usize,
}

#[derive(Debug, Clone)]
pub struct DatabaseTimeouts {
    pub statement_timeout: Duration,
    pub lock_timeout: Duration,
    pub acquire_timeout: Duration,
    pub idle_timeout: Duration,
    pub max_lifetime: Duration,
    pub idle_in_transaction_session_timeout: Duration,
}

pub async fn get_pool(url: &str, max_connections: u32) -> Result<PgPool, sqlx::Error> {
    get_pool_with_timeouts(url, max_connections, DEFAULT_TIMEOUTS).await
}

pub async fn get_pool_with_timeouts(
    url: &str,
    max_connections: u32,
    timeouts: DatabaseTimeouts,
) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(max_connections)
        .acquire_timeout(timeouts.acquire_timeout)
        .test_before_acquire(true)
        .idle_timeout(timeouts.idle_timeout)
        .max_lifetime(timeouts.max_lifetime)
        // Set PostgreSQL session-level timeouts for all queries on this connection
        .after_connect(move |conn, _meta| {
            Box::pin(async move {
                // Convert to i64 with checked conversion to avoid overflow issues
                let stmt_ms: i64 = timeouts
                    .statement_timeout
                    .as_millis()
                    .try_into()
                    .expect("statement_timeout too large");
                let lock_ms: i64 = timeouts
                    .lock_timeout
                    .as_millis()
                    .try_into()
                    .expect("lock_timeout too large");

                // Set statement timeout (PostgreSQL SET commands don't accept bind parameters)
                sqlx::query(&format!("SET statement_timeout = '{stmt_ms}ms'"))
                    .execute(&mut *conn)
                    .await?;

                // Set lock timeout to prevent getting stuck behind long transactions
                sqlx::query(&format!("SET lock_timeout = '{lock_ms}ms'"))
                    .execute(&mut *conn)
                    .await?;

                // Safety net: kill idle transactions to prevent leaked transactions
                // from holding locks forever (doesn't affect normal autocommit reads)
                let idle_tx_secs: i64 = timeouts
                    .idle_in_transaction_session_timeout
                    .as_secs()
                    .try_into()
                    .expect("idle_in_transaction_session_timeout too large");
                sqlx::query(&format!(
                    "SET idle_in_transaction_session_timeout = '{idle_tx_secs}s'"
                ))
                .execute(&mut *conn)
                .await?;

                Ok(())
            })
        })
        .connect(url)
        .await
}

#[async_trait]
impl Client for PgPool {
    fn get_pool_stats(&self) -> Option<PoolStats> {
        Some(PoolStats {
            size: self.size(),
            num_idle: self.num_idle(),
        })
    }

    async fn get_connection(&self) -> Result<PoolConnection<Postgres>, CustomDatabaseError> {
        let conn = self.acquire().await?;
        Ok(conn)
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

/// Determines if a sqlx::Error represents a timeout-related failure
pub fn is_timeout_error(error: &SqlxError) -> bool {
    match error {
        // Pool acquisition timed out
        SqlxError::PoolTimedOut => true,

        // IO-level timeout (network/socket)
        SqlxError::Io(e) if e.kind() == std::io::ErrorKind::TimedOut => true,

        // Protocol text sometimes includes "timeout"
        SqlxError::Protocol(msg) => msg.to_lowercase().contains("timeout"),

        // Database-reported timeouts/cancels
        SqlxError::Database(db_error) => {
            if let Some(code) = db_error.code() {
                let code = code.as_ref();
                // 57014: query_canceled (e.g., statement_timeout)
                // 55P03: lock_not_available (e.g., lock_timeout)
                // 25P03: idle_in_transaction_session_timeout
                code == "57014" || code == "55P03" || code == "25P03"
            } else {
                // Fallback heuristic (less reliable than SQLSTATE)
                let msg = db_error.message().to_lowercase();
                msg.contains("timeout")
                    || msg.contains("canceling")   // Postgres US spelling
                    || msg.contains("cancelling") // just in case
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

    #[test]
    fn test_is_timeout_error_pool_timeout() {
        assert!(is_timeout_error(&SqlxError::PoolTimedOut));
    }

    #[test]
    fn test_is_timeout_error_io_timeout() {
        let io_error = SqlxError::Io(std::io::Error::new(
            std::io::ErrorKind::TimedOut,
            "connection timed out",
        ));
        assert!(is_timeout_error(&io_error));
    }

    #[test]
    fn test_is_timeout_error_io_non_timeout() {
        let io_error = SqlxError::Io(std::io::Error::new(
            std::io::ErrorKind::ConnectionRefused,
            "connection refused",
        ));
        assert!(!is_timeout_error(&io_error));
    }

    #[test]
    fn test_is_timeout_error_protocol_timeout() {
        let protocol_error = SqlxError::Protocol("operation timeout".to_string());
        assert!(is_timeout_error(&protocol_error));

        let protocol_non_timeout = SqlxError::Protocol("invalid protocol".to_string());
        assert!(!is_timeout_error(&protocol_non_timeout));
    }

    #[test]
    fn test_is_timeout_error_database_with_timeout_codes() {
        // Test various timeout-related SQLSTATE codes
        assert!(is_timeout_error(&db_err(
            "canceling statement due to statement timeout",
            Some("57014"),
            ErrorKind::Other
        )));
        assert!(is_timeout_error(&db_err(
            "lock not available",
            Some("55P03"),
            ErrorKind::Other
        )));
        assert!(is_timeout_error(&db_err(
            "terminating connection due to idle-in-transaction timeout",
            Some("25P03"),
            ErrorKind::Other
        )));
    }

    #[test]
    fn test_is_timeout_error_database_non_timeout_codes() {
        // Test non-timeout SQLSTATE codes
        assert!(!is_timeout_error(&db_err(
            "duplicate key value violates unique constraint",
            Some("23505"),
            ErrorKind::UniqueViolation
        )));
        assert!(!is_timeout_error(&db_err(
            "syntax error at or near",
            Some("42601"),
            ErrorKind::Other
        )));
    }

    #[test]
    fn test_is_timeout_error_database_message_fallback() {
        // Test message heuristics when no SQLSTATE code is available
        assert!(is_timeout_error(&db_err(
            "operation timeout",
            None,
            ErrorKind::Other
        )));
        assert!(is_timeout_error(&db_err(
            "canceling statement due to timeout",
            None,
            ErrorKind::Other
        )));
        assert!(is_timeout_error(&db_err(
            "cancelling statement due to timeout",
            None,
            ErrorKind::Other
        )));

        // Non-timeout messages
        assert!(!is_timeout_error(&db_err(
            "column does not exist",
            None,
            ErrorKind::Other
        )));
        assert!(!is_timeout_error(&db_err(
            "relation does not exist",
            None,
            ErrorKind::Other
        )));
    }

    #[test]
    fn test_custom_database_error_conversion_timeout() {
        // Test that CustomDatabaseError::Timeout converts to the timeout error type
        use tokio::time::{timeout, Duration};

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
        // This test just ensures conversion compiles - actual usage depends on consuming crate
        assert!(matches!(timeout_error, CustomDatabaseError::Timeout(_)));
    }

    #[test]
    fn test_custom_database_error_conversion_sqlx_timeout() {
        // Test that sqlx timeout errors are detected by is_timeout_error
        let sqlx_timeout = SqlxError::PoolTimedOut;
        assert!(is_timeout_error(&sqlx_timeout));

        let timeout_error = CustomDatabaseError::Other(sqlx_timeout);
        assert!(matches!(timeout_error, CustomDatabaseError::Other(_)));
    }

    #[test]
    fn test_custom_database_error_conversion_sqlx_non_timeout() {
        // Test that non-timeout sqlx errors are not detected as timeouts
        let sqlx_error = SqlxError::RowNotFound;
        assert!(!is_timeout_error(&sqlx_error));

        let other_error = CustomDatabaseError::Other(sqlx_error);
        assert!(matches!(other_error, CustomDatabaseError::Other(_)));
    }
}
