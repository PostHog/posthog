//! Disaster-recovery durability for the per-process RocksDB state store: a frozen whole-DB
//! `Checkpoint` plus incremental S3 backup/restore.
//!
//! ## Single-DB identity
//!
//! The processor keeps one DB per process holding all 64 partitions (keys are
//! `partition_id`-prefixed), so there is exactly one checkpoint lineage per pod. The per-`(topic,
//! partition)` identity used to key the S3 layout therefore collapses to the two fixed constants
//! below, yielding one stable S3 prefix for the pod. The identity is fixed rather than configurable:
//! a stable prefix is all that matters, and freezing it keeps the S3 layout reproducible across
//! restarts.

pub mod checkpoint;
pub mod config;
pub mod downloader;
pub mod error;
pub mod export;
pub mod import;
pub mod manifest;
pub mod metadata;
pub mod planner;
pub mod recovery;
pub mod s3_client;
pub mod s3_downloader;
pub mod s3_uploader;
pub mod uploader;

/// The single-DB identity's "topic": a fixed store-id string used only to derive the S3 prefix (the
/// whole-DB checkpoint is not tied to any one Kafka topic). See the module docs.
pub const STORE_TOPIC: &str = "cohort_stream_state";
/// The single-DB identity's "partition". Always 0: one DB per pod, not one per Kafka partition.
pub const STORE_PARTITION: i32 = 0;

pub use checkpoint::{
    should_upload, upload_cadence, CheckpointSweeper, TrackedTopic, CHECKPOINT_LOOP_NAME,
};
pub use config::DurabilityConfig;
pub use downloader::CheckpointDownloader;
pub use export::CheckpointExporter;
pub use import::CheckpointImporter;
pub use manifest::{OffsetManifest, MANIFEST_FILENAME, MANIFEST_VERSION};
pub use metadata::{
    hash_prefix_for_partition, store_hash_prefix, CheckpointFile, CheckpointInfo,
    CheckpointMetadata, METADATA_FILENAME,
};
pub use planner::{plan_checkpoint, CheckpointPlan, LocalCheckpointFile};
pub use recovery::{decide_restore_source, run_boot_restore, RestoreOutcome, RestoreSource};
pub use s3_downloader::S3Downloader;
pub use s3_uploader::S3Uploader;
pub use uploader::CheckpointUploader;

pub use error::{
    DownloadCancelledError, ImportTimeoutError, PlanningCancelledError, UploadCancelledError,
};

use std::path::PathBuf;
use tracing::{info, warn};

/// Removes `path` on drop (failure, timeout, cancellation, or panic) unless defused. Shared by both
/// disaster-restore materializers — the S3 import ([`import`]) and the PVC copy ([`recovery`]) — so a
/// failed restore never leaves a partial store directory behind. That guarantee is what lets the next
/// boot's cold-start *outcome* actually start cold rather than reopening a torn store.
pub(super) struct DirCleanupGuard {
    path: PathBuf,
    defused: bool,
}

impl DirCleanupGuard {
    pub(super) fn new(path: PathBuf) -> Self {
        Self {
            path,
            defused: false,
        }
    }

    /// Defuse the guard so the directory survives the drop. Call on success.
    pub(super) fn defuse(mut self) -> PathBuf {
        self.defused = true;
        std::mem::take(&mut self.path)
    }
}

impl Drop for DirCleanupGuard {
    fn drop(&mut self) {
        if !self.defused && self.path.exists() {
            match std::fs::remove_dir_all(&self.path) {
                Ok(_) => info!(
                    path = %self.path.display(),
                    "Dir cleanup guard: removed incomplete store directory"
                ),
                Err(e) => warn!(
                    path = %self.path.display(),
                    error = ?e,
                    "Dir cleanup guard: failed to remove directory, orphan cleaner will handle it"
                ),
            }
        }
    }
}
