use tonic::Status;
use tracing::error;

use crate::storage;

const STORAGE_ERRORS_TOTAL: &str = "personhog_replica_storage_errors_total";

pub fn log_and_convert_error(err: storage::StorageError, operation: &str) -> Status {
    match &err {
        storage::StorageError::Connection(msg) => {
            error!(operation, error = %msg, "Database connection error");
            common_metrics::inc(
                STORAGE_ERRORS_TOTAL,
                &[
                    ("error_type".to_string(), "connection".to_string()),
                    ("operation".to_string(), operation.to_string()),
                ],
                1,
            );
            Status::unavailable(format!("Database unavailable: {msg}"))
        }
        storage::StorageError::PoolExhausted => {
            error!(operation, "Database pool exhausted");
            common_metrics::inc(
                STORAGE_ERRORS_TOTAL,
                &[
                    ("error_type".to_string(), "pool_exhausted".to_string()),
                    ("operation".to_string(), operation.to_string()),
                ],
                1,
            );
            Status::unavailable("Database pool exhausted")
        }
        storage::StorageError::Query(msg) => {
            error!(operation, error = %msg, "Database query error");
            common_metrics::inc(
                STORAGE_ERRORS_TOTAL,
                &[
                    ("error_type".to_string(), "query".to_string()),
                    ("operation".to_string(), operation.to_string()),
                ],
                1,
            );
            Status::internal(format!("Database error: {msg}"))
        }
    }
}
