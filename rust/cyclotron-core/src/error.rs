use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum QueueError {
    #[error("sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
    #[error("Unknown job id: {0}")]
    UnknownJobId(Uuid), // Happens when someone tries to update a job through a QueueManager that wasn't dequeue or was already flushed
    #[error("Job {0} flushed without a new state, which would leave it in a running state forever (or until reaped)")]
    FlushWithoutNextState(Uuid),
    #[error("Invalid lock {0} used to update job {1}. This usually means a job has been reaped from under a worker - did you forget to set the heartbeat?")]
    InvalidLock(Uuid, Uuid),
    #[error("Shard over capacity {0} for this manager, insert aborted")]
    ShardFull(u64),
    #[error("Timed waiting for shard to have capacity")]
    TimedOutWaitingForCapacity,
}
