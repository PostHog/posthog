use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointConfig {
    /// How often to trigger a checkpoint attempt for all locally-hosted partition stores
    pub checkpoint_interval: Duration,

    /// How many incremental checkpoint attempts to perform between full
    /// uploads of all checkpoint files. If 0, we allways perform a
    /// full upload on every attempt
    pub checkpoint_full_upload_interval: u32,

    /// Base directory for local checkpoints
    pub local_checkpoint_dir: String,

    /// S3 bucket for checkpoint uploads
    pub s3_bucket: String,

    /// S3 key prefix (bucket namespace) for checkpoints attempts
    pub s3_key_prefix: String,

    /// AWS region for S3
    pub aws_region: String,

    /// Maximum number of concurrent checkpoint attempts to perform on a single node.
    /// NOTE: checkpoint attempts are unique to a given partition; no two for the same
    /// partition can be in-flight at the same time
    pub max_concurrent_checkpoints: usize,

    /// Polling interval to check if a concurrent checkpoint attempt slot
    /// has become available when max_concurrent_checkpoints slots are occupied
    pub checkpoint_gate_interval: Duration,

    /// Timeout for checkpoint worker graceful shutdown (applied in CheckpointManager::stop)
    pub checkpoint_worker_shutdown_timeout: Duration,

    /// Number of hours prior to "now" that the checkpoint import mechanism
    /// will search for valid checkpoint attempts in a DR recovery or HPA
    /// autoscaling scenario where net-new Persistent Volumes are created
    pub checkpoint_import_window_hours: u32,

    /// Timeout for S3 operations (including all retry attempts)
    pub s3_operation_timeout: Duration,

    /// Timeout for a single S3 operation attempt
    pub s3_attempt_timeout: Duration,
}

impl Default for CheckpointConfig {
    fn default() -> Self {
        Self {
            // NOTE! production & local dev defaults can be overridden in top-level config.rs
            // or env vars; assume these defaults are only applied as-is in unit tests and CI
            checkpoint_interval: Duration::from_secs(300),
            checkpoint_full_upload_interval: 10, // create a full checkpoint every 10 attempts per partition
            local_checkpoint_dir: "./checkpoints".to_string(),
            s3_bucket: "".to_string(),
            s3_key_prefix: "deduplication-checkpoints".to_string(),
            aws_region: "us-east-1".to_string(),
            max_concurrent_checkpoints: 3,
            checkpoint_gate_interval: Duration::from_millis(200),
            checkpoint_worker_shutdown_timeout: Duration::from_secs(10),
            checkpoint_import_window_hours: 24,
            s3_operation_timeout: Duration::from_secs(120),
            s3_attempt_timeout: Duration::from_secs(20),
        }
    }
}
