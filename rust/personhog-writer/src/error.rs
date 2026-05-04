//! Error vocabulary shared across the pg, store, and writer layers.
//!
//! Error *sources* (sqlx, tokio JoinError) are translated into these types
//! in the modules that own them: `pg::classify_error` for sqlx errors and
//! `store::classify_join_error` for task panics.

/// Classification of write errors. Determines retry strategy.
#[derive(Debug, Clone, Copy)]
pub enum WriteErrorKind {
    /// Retrying the same operation may succeed.
    Transient,
    /// Properties exceed the DB size constraint. Trimming may help.
    PropertiesSizeViolation,
    /// Unrecoverable data error. Skip this record.
    Data,
}

/// Error from a per-row or per-chunk write operation. Carries the DB error
/// message so it can surface in ingestion warnings for user-facing debugging.
#[derive(Debug)]
pub struct WriteError {
    pub message: String,
    pub kind: WriteErrorKind,
}

impl std::fmt::Display for WriteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

/// Unrecoverable error from a batch operation — typically a chunk task panic.
/// The caller must escalate; the underlying records will be redelivered from
/// Kafka after restart since the offset has not been committed.
#[derive(Debug)]
pub struct FatalError {
    pub message: String,
}

impl std::fmt::Display for FatalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}
