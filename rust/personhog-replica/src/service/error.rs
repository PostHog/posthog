use personhog_common::grpc::current_client_name;
use tonic::Status;
use tracing::{error, warn};

use crate::storage;

const STORAGE_ERRORS_TOTAL: &str = "personhog_replica_storage_errors_total";

pub fn log_and_convert_error(err: storage::StorageError, operation: &str) -> Status {
    let client = current_client_name();
    match &err {
        storage::StorageError::Connection(msg) => {
            error!(operation, error = %msg, "Database connection error");
            common_metrics::inc(
                STORAGE_ERRORS_TOTAL,
                &[
                    ("error_type".to_string(), "connection".to_string()),
                    ("operation".to_string(), operation.to_string()),
                    ("client".to_string(), client.to_string()),
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
                    ("client".to_string(), client.to_string()),
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
                    ("client".to_string(), client.to_string()),
                ],
                1,
            );
            Status::internal(format!("Database error: {msg}"))
        }
        storage::StorageError::NotFound(msg) => Status::not_found(msg.clone()),
        storage::StorageError::FailedPrecondition(msg) => {
            warn!(operation, error = %msg, "Failed precondition");
            common_metrics::inc(
                STORAGE_ERRORS_TOTAL,
                &[
                    ("error_type".to_string(), "failed_precondition".to_string()),
                    ("operation".to_string(), operation.to_string()),
                    ("client".to_string(), client.to_string()),
                ],
                1,
            );
            Status::failed_precondition(msg.clone())
        }
    }
}

#[cfg(test)]
mod tests {
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    use tonic::Code;

    use super::*;

    #[test]
    fn failed_precondition_is_counted() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        let status = log_and_convert_error(
            storage::StorageError::FailedPrecondition("persons are claimed".to_string()),
            "delete_persons",
        );

        assert_eq!(status.code(), Code::FailedPrecondition);
        let counted: u64 = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, _, _, _)| {
                key.key().name() == STORAGE_ERRORS_TOTAL
                    && key
                        .key()
                        .labels()
                        .any(|l| l.key() == "error_type" && l.value() == "failed_precondition")
            })
            .map(|(_, _, _, value)| match value {
                DebugValue::Counter(n) => n,
                _ => 0,
            })
            .sum();
        assert_eq!(counted, 1);
    }
}
