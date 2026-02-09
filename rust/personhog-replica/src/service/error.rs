use tonic::Status;
use tracing::error;

use crate::storage;

pub fn log_and_convert_error(err: storage::StorageError, operation: &str) -> Status {
    match &err {
        storage::StorageError::Connection(msg) => {
            error!(operation, error = %msg, "Database connection error");
            Status::unavailable(format!("Database unavailable: {msg}"))
        }
        storage::StorageError::PoolExhausted => {
            error!(operation, "Database pool exhausted");
            Status::unavailable("Database pool exhausted")
        }
        storage::StorageError::Query(msg) => {
            error!(operation, error = %msg, "Database query error");
            Status::internal(format!("Database error: {msg}"))
        }
    }
}
