//! Resolved knobs for the durability layer (S3 client, uploader, downloader, importer).

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Default maximum age (seconds) of a local checkpoint before the local store is considered stale and
/// the service falls back to S3 import. 2 hours.
pub const DEFAULT_LOCAL_CHECKPOINT_MAX_STALENESS_SECS: u64 = 7200;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DurabilityConfig {
    /// Base directory for local checkpoints (a subtree separate from the live store path).
    pub local_checkpoint_dir: String,

    /// S3 bucket for checkpoint uploads.
    pub s3_bucket: String,

    /// S3 key prefix (bucket namespace) for checkpoint attempts.
    pub s3_key_prefix: String,

    /// AWS region for S3.
    pub aws_region: Option<String>,

    /// S3 endpoint URL (for non-AWS S3-compatible stores like MinIO/SeaweedFS).
    pub s3_endpoint: Option<String>,

    /// S3 access key (for local dev without IAM role).
    pub s3_access_key_id: Option<String>,

    /// S3 secret key (for local dev without IAM role).
    pub s3_secret_access_key: Option<String>,

    /// Force path-style S3 URLs (required for MinIO/SeaweedFS).
    pub s3_force_path_style: bool,

    /// Number of hours prior to "now" that the checkpoint import mechanism will search for valid
    /// checkpoint attempts in a DR recovery scenario where a net-new Persistent Volume was created.
    pub checkpoint_import_window_hours: u32,

    /// Timeout for S3 operations (including all retry attempts).
    pub s3_operation_timeout: Duration,

    /// Timeout for a single S3 operation attempt.
    pub s3_attempt_timeout: Duration,

    /// Maximum number of retries for S3 operations before giving up.
    pub s3_max_retries: usize,

    /// Number of recent historical checkpoint attempts to try to import, starting from most recent,
    /// when importing from remote storage. A failed download or corrupt files falls back to the next
    /// most recent checkpoint attempt this many times.
    pub checkpoint_import_attempt_depth: usize,

    /// Maximum concurrent S3 file downloads during checkpoint import. Bounds the number of in-flight
    /// HTTP connections (and thus memory).
    pub max_concurrent_checkpoint_file_downloads: usize,

    /// Maximum concurrent S3 file uploads during checkpoint export. Controls the `LimitStore`
    /// semaphore that bounds concurrent S3 HTTP requests.
    pub max_concurrent_checkpoint_file_uploads: usize,

    /// Maximum number of upload futures actively polled (files open with read buffers and BufWriters)
    /// per checkpoint. Controls the `buffer_unordered` window to bound memory independently from the
    /// S3 HTTP concurrency limit above. Each active buffer consumes ~18MB (8MB read buffer + ~10MB
    /// BufWriter).
    pub max_upload_buffers: usize,

    /// Maximum time allowed for a complete checkpoint import. This includes listing checkpoints,
    /// downloading metadata, and downloading all files. Should be less than Kafka max.poll.interval.ms
    /// to prevent consumer group kicks.
    pub checkpoint_import_timeout: Duration,

    /// Maximum age of a local checkpoint before the local store is considered stale and the service
    /// falls back to S3 import. Separate from `checkpoint_import_window_hours` (the S3 listing window):
    /// local staleness must be tighter because if a pod was down for longer than this, another pod
    /// likely consumed the partition and local data is behind.
    pub local_checkpoint_max_staleness: Duration,
}

impl Default for DurabilityConfig {
    fn default() -> Self {
        Self {
            local_checkpoint_dir: "./checkpoints".to_string(),
            s3_bucket: String::new(),
            s3_key_prefix: "cohort-stream-checkpoints".to_string(),
            aws_region: None,
            s3_endpoint: None,
            s3_access_key_id: None,
            s3_secret_access_key: None,
            s3_force_path_style: false,
            checkpoint_import_window_hours: 24,
            s3_operation_timeout: Duration::from_secs(120),
            s3_attempt_timeout: Duration::from_secs(20),
            s3_max_retries: 3,
            checkpoint_import_attempt_depth: 10,
            max_concurrent_checkpoint_file_downloads: 40,
            max_concurrent_checkpoint_file_uploads: 40,
            max_upload_buffers: 40,
            checkpoint_import_timeout: Duration::from_secs(240),
            local_checkpoint_max_staleness: Duration::from_secs(
                DEFAULT_LOCAL_CHECKPOINT_MAX_STALENESS_SECS,
            ),
        }
    }
}
