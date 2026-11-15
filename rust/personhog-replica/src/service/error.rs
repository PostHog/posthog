use personhog_common::grpc::{current_client_name, db_timeout_status};
use tonic::Status;
use tracing::{error, warn};

use crate::storage;

const STORAGE_ERRORS_TOTAL: &str = "personhog_replica_storage_errors_total";

pub fn log_and_convert_error(err: storage::StorageError, operation: &str) -> Status {
    if !matches!(err, storage::StorageError::NotFound(_)) {
        common_metrics::inc(
            STORAGE_ERRORS_TOTAL,
            &[
                ("error_type".to_string(), err.error_type().to_string()),
                ("operation".to_string(), operation.to_string()),
                ("client".to_string(), current_client_name().to_string()),
            ],
            1,
        );
    }
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
        storage::StorageError::Timeout { kind, .. } => {
            error!(operation, error = %err, "Database timeout");
            db_timeout_status(err.to_string(), kind)
        }
        storage::StorageError::NotFound(msg) => Status::not_found(msg),
        storage::StorageError::FailedPrecondition(msg) => {
            warn!(operation, error = %msg, "Failed precondition");
            Status::failed_precondition(msg)
        }
    }
}

#[cfg(test)]
mod tests {
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    use personhog_common::grpc::DB_TIMEOUT_METADATA_KEY;
    use rstest::rstest;
    use tonic::Code;

    use super::*;

    fn timeout(kind: storage::TimeoutKind) -> storage::StorageError {
        storage::StorageError::Timeout {
            kind,
            message: "canceling statement".to_string(),
        }
    }

    #[rstest]
    #[case::failed_precondition(
        storage::StorageError::FailedPrecondition("persons are claimed".to_string()),
        Code::FailedPrecondition,
        "failed_precondition"
    )]
    #[case::statement_timeout(
        timeout(storage::TimeoutKind::Statement),
        Code::DeadlineExceeded,
        "statement_timeout"
    )]
    #[case::lock_timeout(
        timeout(storage::TimeoutKind::Lock),
        Code::DeadlineExceeded,
        "lock_timeout"
    )]
    fn storage_error_is_counted_by_type(
        #[case] err: storage::StorageError,
        #[case] expected_code: Code,
        #[case] expected_error_type: &str,
    ) {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);

        let status = log_and_convert_error(err, "delete_persons");

        assert_eq!(status.code(), expected_code);
        assert_eq!(
            status
                .metadata()
                .get(DB_TIMEOUT_METADATA_KEY)
                .and_then(|v| v.to_str().ok()),
            (expected_code == Code::DeadlineExceeded).then_some(expected_error_type)
        );
        let counted: u64 = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, _, _, _)| {
                key.key().name() == STORAGE_ERRORS_TOTAL
                    && key
                        .key()
                        .labels()
                        .any(|l| l.key() == "error_type" && l.value() == expected_error_type)
            })
            .map(|(_, _, _, value)| match value {
                DebugValue::Counter(n) => n,
                _ => 0,
            })
            .sum();
        assert_eq!(counted, 1);
    }
}
