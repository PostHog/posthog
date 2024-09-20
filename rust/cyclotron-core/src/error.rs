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
}

impl JobError {
    pub fn to_label(&self) -> &'static str {
        match self {
            JobError::UnknownJobId(_) => "unknown_job_id",
            JobError::InvalidLock(_, _) => "invalid_lock",
            JobError::FlushWithoutNextState(_) => "flush_without_next_state",
            JobError::DeadlineExceeded(_) => "deadline_exceeded",
            JobError::UpdateDropped => "update_dropped",
        }
    }
}
