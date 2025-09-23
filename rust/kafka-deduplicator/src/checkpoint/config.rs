use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointConfig {
    /// How often to trigger a checkpoint
    pub checkpoint_interval: Duration,

    /// How often to cleanup local checkpoints
    pub cleanup_interval: Duration,

    /// Base directory for local checkpoints
    pub local_checkpoint_dir: String,

    /// S3 bucket for checkpoint uploads
    pub s3_bucket: String,

    /// S3 key prefix for checkpoints
    pub s3_key_prefix: String,

    // how often should we perform a full checkpoint vs. incremental.
    // if 0, then we will always do full checkpoints
    pub full_upload_interval: u32,

    /// AWS region for S3
    pub aws_region: String,

    /// Maximum number of local checkpoints to keep around *per partition*
    pub max_local_checkpoints: usize,

    /// Maximum number of hours for which any local checkpoint is retained
    pub max_checkpoint_retention_hours: u32,

    /// Maximum number of concurrent checkpoints to perform
    pub max_concurrent_checkpoints: usize,

    /// How often to attempt to check if a slot is available
    /// when max_concurrent_checkpoints slots are occupied
    pub checkpoint_gate_interval: Duration,

    /// Timeout for checkpoint worker graceful shutdown (applied in CheckpointManager::stop)
    pub checkpoint_worker_shutdown_timeout: Duration,

    /// Timeout for S3 operations
    pub s3_timeout: Duration,
}

impl Default for CheckpointConfig {
    fn default() -> Self {
        Self {
            // NOTE! production & local dev defaults can be overridden in top-level config.rs
            //or env vars; assume these defaults are only applied as-is in unit tests and CI
            checkpoint_interval: Duration::from_secs(300), // 5 minutes (TBD)
            cleanup_interval: Duration::from_secs(1320),   // 22 minutes (TBD)
            local_checkpoint_dir: "./checkpoints".to_string(),
            s3_bucket: "".to_string(),
            s3_key_prefix: "deduplication-checkpoints".to_string(),
            full_upload_interval: 0, // TODO: always full checkpoints until we impl incremental
            aws_region: "us-east-1".to_string(),
            max_local_checkpoints: 10,
            max_checkpoint_retention_hours: 72,
            max_concurrent_checkpoints: 3,
            checkpoint_gate_interval: Duration::from_millis(200),
            checkpoint_worker_shutdown_timeout: Duration::from_secs(10),
            s3_timeout: Duration::from_secs(300), // 5 minutes
        }
    }
}
