use thiserror::Error;

/// Enumeration of parsing errors in PgQueue.
#[derive(Error, Debug)]
pub enum ParseError {
    #[error("{0} is not a valid JobStatus")]
    ParseJobStatusError(String),
    #[error("{0} is not a valid HttpMethod")]
    ParseHttpMethodError(String),
    #[error("transaction was already closed")]
    TransactionAlreadyClosedError,
}

/// Enumeration of database-related errors in PgQueue.
/// Errors that can originate from sqlx and are wrapped by us to provide additional context.
#[derive(Error, Debug)]
pub enum DatabaseError {
    #[error("pool creation failed with: {error}")]
    PoolCreationError { error: sqlx::Error },
    #[error("connection failed with: {error}")]
    ConnectionError { error: sqlx::Error },
    #[error("{command} query failed with: {error}")]
    QueryError { command: String, error: sqlx::Error },
    #[error("could not serialize jsonb field: {error}")]
    SerializationError { error: serde_json::Error },
    #[error("transaction {command} failed with: {error}")]
    TransactionError { command: String, error: sqlx::Error },
    #[error("transaction was already closed")]
    TransactionAlreadyClosedError,
}

/// An error that occurs when a job cannot be retried.
/// Returns the underlying job so that a client can fail it.
#[derive(Error, Debug)]
#[error("retry is an invalid state for this job: {error}")]
pub struct RetryInvalidError<T> {
    pub job: T,
    pub error: String,
}

/// Enumeration of errors that can occur when retrying a job.
/// They are in a separate enum a failed retry could be returning the underlying job.
#[derive(Error, Debug)]
pub enum RetryError<T> {
    #[error(transparent)]
    DatabaseError(#[from] DatabaseError),
    #[error(transparent)]
    RetryInvalidError(#[from] RetryInvalidError<T>),
}
