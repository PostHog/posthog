use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum QueueError {
    #[error("sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
    #[error("Unknown job id: {0}")]
    UnknownJobId(Uuid), // Happens when someone tries to update a job through a QueueManager that wasn't dequeue or was already flushed
    #[error("Job {0} flushed without a new state, which would leave it in a running state forever (or until reaped)")]
    FlushWithoutNextState(Uuid),
}
