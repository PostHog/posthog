use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum QueueError {
    #[error("sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
    #[error("Shard over capacity {0} for this manager, insert aborted")]
    ShardFull(u64),
    #[error("Timed waiting for shard to have capacity")]
    TimedOutWaitingForCapacity,
    #[error(transparent)]
    JobError(#[from] JobError),
    #[error("vm_state compression error: {0}")]
    CompressionError(String),
    #[error("writing in-mem CSV buffer at {0}: {1}")]
    CsvError(&'static str, csv::Error),
}

impl QueueError {
    pub fn is_missing_relation(&self, relation: &str) -> bool {
        match self {
            QueueError::SqlxError(sqlx::Error::Database(db_error)) => {
                is_missing_relation_error(db_error.code().as_deref(), db_error.message(), relation)
            }
            _ => false,
        }
    }
}

fn is_missing_relation_error(code: Option<&str>, message: &str, relation: &str) -> bool {
    let quoted_relation = format!("\"{relation}\"");
    code == Some("42P01") && message.contains(&quoted_relation)
}

#[derive(Debug, thiserror::Error)]
pub enum JobError {
    #[error("Unknown job id: {0}")]
    UnknownJobId(Uuid),
    #[error("Invalid lock id: {0} for job {1}")]
    InvalidLock(Uuid, Uuid),
    #[error("Cannot flush job {0} without a next state")]
    FlushWithoutNextState(Uuid),
    #[error("Deadline to flush update for job {0} exceeded")]
    DeadlineExceeded(Uuid),
    #[error("Update dropped before being flushed.")]
    UpdateDropped,
    #[error("vm_state compression error: {0}")]
    CompressionError(String),
}

#[cfg(test)]
mod tests {
    use super::is_missing_relation_error;

    #[test]
    fn detects_missing_relation_error_cases() {
        let cases = [
            (
                Some("42P01"),
                "relation \"cyclotron_jobs\" does not exist",
                "cyclotron_jobs",
                true,
            ),
            (
                Some("42P01"),
                "relation \"some_other_table\" does not exist",
                "cyclotron_jobs",
                false,
            ),
            (
                Some("23505"),
                "duplicate key value violates unique constraint",
                "cyclotron_jobs",
                false,
            ),
            (
                None,
                "relation \"cyclotron_jobs\" does not exist",
                "cyclotron_jobs",
                false,
            ),
        ];

        for (code, message, relation, expected) in cases {
            assert_eq!(
                is_missing_relation_error(code, message, relation),
                expected,
                "unexpected result for code={code:?}, message={message}, relation={relation}"
            );
        }
    }
}
