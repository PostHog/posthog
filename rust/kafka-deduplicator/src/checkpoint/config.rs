use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckpointConfig {
    /// How often to trigger a checkpoint attempt for all locally-hosted partition stores
    pub checkpoint_interval: Duration,

    /// How many incremental checkpoint attempts to perform between full
    /// uploads of all checkpoint files. If 0, we always perform a full upload on every attempt.
    pub checkpoint_full_upload_interval: u32,

    /// Base directory for local checkpoints
    pub local_checkpoint_dir: String,

    /// S3 bucket for checkpoint uploads
    pub s3_bucket: String,

    /// S3 key prefix (bucket namespace) for checkpoints attempts
    pub s3_key_prefix: String,

    /// AWS region for S3
    pub aws_region: Option<String>,

    /// S3 endpoint URL (for non-AWS S3-compatible stores like MinIO)
    pub s3_endpoint: Option<String>,

    /// S3 access key (for local dev without IAM role)
    pub s3_access_key_id: Option<String>,

    /// S3 secret key (for local dev without IAM role)
    pub s3_secret_access_key: Option<String>,

    /// Force path-style S3 URLs (required for MinIO)
    pub s3_force_path_style: bool,

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

    /// Maximum number of retries for S3 operations before giving up
    pub s3_max_retries: usize,

    /// Number of recent historical checkpoint attempts to try to import,
    /// starting from most recent, when attempting to import from remote
    /// storage. A failed download or corrupt files will result in fallback
    /// to the next most recent checkpoint attempt this many times
    pub checkpoint_import_attempt_depth: usize,

    /// Maximum concurrent S3 file downloads during checkpoint import.
    /// Limits memory usage by bounding the number of in-flight HTTP connections.
    /// This is critical during rebalance when many partitions are assigned simultaneously.
    pub max_concurrent_checkpoint_file_downloads: usize,

    /// Maximum concurrent S3 file uploads during checkpoint export.
    /// Less critical than downloads since uploads are already bounded by max_concurrent_checkpoints,
    /// but provides additional defense in depth.
    pub max_concurrent_checkpoint_file_uploads: usize,

    /// Maximum time allowed for a complete checkpoint import for a single partition.
    /// This includes listing checkpoints, downloading metadata, and downloading all files.
    /// Should be less than kafka max.poll.interval.ms to prevent consumer group kicks.
    pub checkpoint_partition_import_timeout: Duration,
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
            aws_region: None,
            s3_endpoint: None,
            s3_access_key_id: None,
            s3_secret_access_key: None,
            s3_force_path_style: false,
            max_concurrent_checkpoints: 3,
            checkpoint_gate_interval: Duration::from_millis(200),
            checkpoint_worker_shutdown_timeout: Duration::from_secs(10),
            checkpoint_import_window_hours: 24,
            s3_operation_timeout: Duration::from_secs(120),
            s3_attempt_timeout: Duration::from_secs(20),
            s3_max_retries: 3,
            checkpoint_import_attempt_depth: 10,
            max_concurrent_checkpoint_file_downloads: 50,
            max_concurrent_checkpoint_file_uploads: 25,
            checkpoint_partition_import_timeout: Duration::from_secs(240),
        }
    }
}
