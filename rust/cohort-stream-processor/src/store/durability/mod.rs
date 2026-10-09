//! Disaster-recovery durability for the per-process RocksDB state store: frozen whole-DB
//! checkpoints on the local volume, uploaded incrementally to S3, and a boot that restores one
//! safely when the live store is gone.
//!
//! ## One lineage per pod
//!
//! The processor keeps one DB per process holding every slice it owns (keys are
//! `partition_id`-prefixed), so each pod has one checkpoint lineage, named by its StatefulSet
//! ordinal ([`CheckpointLineage`]). Every local path and S3 key derives from it, so two pods never
//! read or write each other's checkpoints.

pub mod checkpoint;
pub mod config;
pub mod downloader;
pub mod error;
pub mod export;
pub mod import;
pub mod lineage;
pub mod manifest;
pub mod metadata;
pub mod planner;
pub mod recovery;
pub mod restore_plan;
pub mod s3_client;
pub mod s3_downloader;
pub mod s3_uploader;
pub mod stage;
pub mod uploader;

/// The fixed first segment of every lineage's paths. The whole-DB checkpoint is not tied to any one
/// Kafka topic; the name only has to stay stable, because ordinal 0's S3 hash derives from it.
pub const STORE_TOPIC: &str = "cohort_stream_state";

pub use checkpoint::{upload_cadence, CheckpointSweeper};
pub use config::DurabilityConfig;
pub use downloader::CheckpointDownloader;
pub use export::CheckpointExporter;
pub use import::CheckpointImporter;
pub use lineage::{CheckpointLineage, NotAnOrdinalPod, PodOrdinal};
pub use manifest::{OffsetManifest, MANIFEST_FILENAME};
pub use metadata::{
    CheckpointFile, CheckpointInfo, CheckpointMetadata, MetadataError, METADATA_FILENAME,
};
pub use planner::{plan_checkpoint, CheckpointPlan, LocalCheckpointFile};
pub use recovery::open_store;
pub use s3_downloader::S3Downloader;
pub use s3_uploader::S3Uploader;
pub use stage::{ensure_one_filesystem, PendingRestore, SettleError, MARKER_FILENAME};
pub use uploader::CheckpointUploader;

pub use error::{DownloadCancelledError, PlanningCancelledError, UploadCancelledError};

use std::path::PathBuf;
use tracing::{info, warn};

/// Removes `path` on drop (failure, timeout, cancellation, or panic) unless defused, so a failed
/// restore leaves no partial staging directory behind. A kill runs no destructor; the next boot
/// deletes the stage before it decides.
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
                    "Dir cleanup guard: removed an incomplete staging directory"
                ),
                Err(e) => warn!(
                    path = %self.path.display(),
                    error = ?e,
                    "Dir cleanup guard: failed to remove the directory; the next boot deletes it"
                ),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn cleanup_guard_removes_the_directory_unless_defused() {
        let tmp_dir = TempDir::new().unwrap();
        let kept = tmp_dir.path().join("kept");
        let dropped = tmp_dir.path().join("dropped");
        for dir in [&kept, &dropped] {
            std::fs::create_dir_all(dir).unwrap();
            std::fs::write(dir.join("000001.sst"), b"sst").unwrap();
        }

        assert_eq!(DirCleanupGuard::new(kept.clone()).defuse(), kept);
        drop(DirCleanupGuard::new(dropped.clone()));

        assert!(kept.join("000001.sst").exists());
        assert!(!dropped.exists());
    }
}
