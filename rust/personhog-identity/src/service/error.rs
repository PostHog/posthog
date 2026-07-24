use personhog_common::grpc::current_client_name;
use tonic::Status;
use tracing::error;

use crate::storage;

const STORAGE_ERRORS_TOTAL: &str = "personhog_identity_storage_errors_total";

pub fn log_and_convert_error(err: storage::StorageError, operation: &str) -> Status {
    let client = current_client_name();
    let error_type = match &err {
        storage::StorageError::Connection(_) => "connection",
        storage::StorageError::PoolExhausted => "pool_exhausted",
        storage::StorageError::Query(_) => "query",
        storage::StorageError::NotFound(_) => "not_found",
        storage::StorageError::FailedPrecondition(_) => "failed_precondition",
    };
    common_metrics::inc(
        STORAGE_ERRORS_TOTAL,
        &[
            ("error_type".to_string(), error_type.to_string()),
            ("operation".to_string(), operation.to_string()),
            ("client".to_string(), client.to_string()),
        ],
        1,
    );
    match err {
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
        storage::StorageError::NotFound(msg) => Status::not_found(msg),
        storage::StorageError::FailedPrecondition(msg) => Status::failed_precondition(msg),
    }
}
