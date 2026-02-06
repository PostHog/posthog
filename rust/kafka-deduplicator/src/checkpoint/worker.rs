use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use super::{
    plan_checkpoint, CheckpointExporter, CheckpointInfo, CheckpointMetadata, UploadCancelledError,
};
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::types::Partition;
use crate::metrics_const::{
    CHECKPOINT_DURATION_HISTOGRAM, CHECKPOINT_FILE_COUNT_HISTOGRAM, CHECKPOINT_SIZE_HISTOGRAM,
    CHECKPOINT_WORKER_STATUS_COUNTER,
};
use crate::store::{DeduplicationStore, LocalCheckpointInfo};

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use metrics;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

/// Worker that handles checkpoint processing for individual partitions
pub struct CheckpointWorker {
    /// Worker ID for logging
    worker_id: u32,

    /// Local base directory for checkpoint files
    local_base_dir: PathBuf,

    /// Remote namespace for checkpoint files
    remote_namespace: String,

    /// Target topic and partition
    partition: Partition,

    /// Timestamp of this checkpoint attempt
    attempt_timestamp: DateTime<Utc>,

    /// Checkpoint export module
    exporter: Option<Arc<CheckpointExporter>>,

    /// Offset tracker for querying committed consumer and producer offsets
    offset_tracker: Option<Arc<OffsetTracker>>,

    /// Whether this is a test worker
    test_mode: bool,
}

impl CheckpointWorker {
    pub fn new(
        worker_id: u32,
        local_base_dir: &Path,
        remote_namespace: String,
        partition: Partition,
        attempt_timestamp: DateTime<Utc>,
        exporter: Option<Arc<CheckpointExporter>>,
        offset_tracker: Option<Arc<OffsetTracker>>,
    ) -> Self {
        Self {
            worker_id,
            local_base_dir: local_base_dir.to_path_buf(),
            remote_namespace,
            partition,
            attempt_timestamp,
            exporter,
            offset_tracker,
            test_mode: false,
        }
    }

    pub fn new_for_testing(
        worker_id: u32,
        local_base_dir: &Path,
        remote_namespace: &str,
        partition: Partition,
        attempt_timestamp: DateTime<Utc>,
        exporter: Option<Arc<CheckpointExporter>>,
    ) -> Self {
        Self {
            worker_id,
            local_base_dir: local_base_dir.to_path_buf(),
            remote_namespace: remote_namespace.to_string(),
            partition,
            attempt_timestamp,
            exporter,
            offset_tracker: None,
            test_mode: true,
        }
    }

    /// Perform a complete checkpoint operation: create, export, and cleanup.
    /// Returns checkpoint info on success, None if export was skipped.
    pub async fn checkpoint_partition(
        &self,
        store: &DeduplicationStore,
        previous_metadata: Option<&CheckpointMetadata>,
    ) -> Result<Option<CheckpointInfo>> {
        self.checkpoint_partition_cancellable(store, previous_metadata, None, None)
            .await
    }

    /// Perform a complete checkpoint operation with cancellation support.
    /// If cancel_token is provided and cancelled during export, returns an error early.
    ///
    /// The optional `cancel_cause` is used for metrics when cancelled (e.g., "rebalance" or "shutdown").
    pub async fn checkpoint_partition_cancellable(
        &self,
        store: &DeduplicationStore,
        previous_metadata: Option<&CheckpointMetadata>,
        cancel_token: Option<&CancellationToken>,
        cancel_cause: Option<&str>,
    ) -> Result<Option<CheckpointInfo>> {
        // Create the local checkpoint
        let rocks_metadata = self.create_checkpoint(store).await?;

        // Export checkpoint with cancellation support
        let result = self
            .export_checkpoint_cancellable(
                &rocks_metadata,
                previous_metadata,
                cancel_token,
                cancel_cause,
            )
            .await;

        // Clean up temp checkpoint directory (skip in test mode to allow verification)
        if !self.test_mode {
            self.cleanup_checkpoint().await;
        }

        result
    }

    /// Create a local checkpoint (step 1 of checkpoint process)
    /// Returns RocksDB metadata about the checkpoint
    pub async fn create_checkpoint(
        &self,
        store: &DeduplicationStore,
    ) -> Result<LocalCheckpointInfo> {
        info!(
            self.worker_id,
            partition = self.partition.to_string(),
            attempt_timestamp = self.attempt_timestamp.to_string(),
            "Checkpoint worker: initializing checkpoint"
        );

        // Ensure local checkpoint directory exists - results observed internally, safe to bubble up
        self.create_partition_checkpoint_directory().await?;

        // this creates the local RocksDB checkpoint - results observed internally, safe to bubble up
        let rocks_metadata = self.create_local_partition_checkpoint(store).await?;

        // update store metrics - this can fail without blocking the checkpoint attempt
        if let Err(e) = store.update_metrics() {
            warn!(
                self.worker_id,
                partition = self.partition.to_string(),
                attempt_timestamp = self.attempt_timestamp.to_string(),
                "Checkpoint worker: failed store metrics update after local checkpoint: {}",
                e
            );
        }

        Ok(rocks_metadata)
    }

    /// Clean up the temporary checkpoint directory (step 3 of checkpoint process)
    pub async fn cleanup_checkpoint(&self) {
        info!(
            self.worker_id,
            local_attempt_path = self.get_local_attempt_path().to_string_lossy().to_string(),
            "Checkpoint worker: deleting local attempt directory",
        );

        if let Err(e) = tokio::fs::remove_dir_all(&self.get_local_attempt_path()).await {
            error!(
                self.worker_id,
                local_attempt_path = self.get_local_attempt_path().to_string_lossy().to_string(),
                "Checkpoint worker: failed to clean up local attempt directory: {}",
                e
            );
        }
    }

    async fn create_partition_checkpoint_directory(&self) -> Result<()> {
        // oddly, the RocksDB client likes to create the final directory in the
        // checkpoint path and will error if the parent dirs do not exist, or
        // full path exists ahead of the checkpoint attempt. Here, we only
        // create the directories above the final timestamp-based dir that
        // will house the checkpoint files
        let base_attempt_path = self.get_local_attempt_path();
        let base_path = base_attempt_path
            .parent()
            .context("Checkpoint worker: failed to get parent directory")?;
        if let Err(e) = tokio::fs::create_dir_all(&base_path).await {
            let tags = [("result", "error"), ("cause", "create_local_dir")];
            metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
            error!(
                self.worker_id,
                local_base_path = base_path.to_string_lossy().to_string(),
                "Checkpoint worker: failed to create local directory: {}",
                e
            );

            return Err(anyhow::anyhow!(e));
        }

        Ok(())
    }

    async fn create_local_partition_checkpoint(
        &self,
        store: &DeduplicationStore,
    ) -> Result<LocalCheckpointInfo> {
        let start_time = Instant::now();
        let local_attempt_path = self.get_local_attempt_path();

        // TODO: this should accept CheckpointMode argument to implement incremental local checkpoint step
        match store.create_checkpoint_with_metadata(&local_attempt_path) {
            Ok(rocks_metadata) => {
                let checkpoint_duration = start_time.elapsed();
                metrics::histogram!(CHECKPOINT_DURATION_HISTOGRAM)
                    .record(checkpoint_duration.as_secs_f64());

                metrics::histogram!(CHECKPOINT_FILE_COUNT_HISTOGRAM)
                    .record(rocks_metadata.sst_files.len() as f64);
                if let Ok(checkpoint_size) = Self::get_directory_size(&local_attempt_path).await {
                    metrics::histogram!(CHECKPOINT_SIZE_HISTOGRAM).record(checkpoint_size as f64);
                }

                info!(
                    self.worker_id,
                    local_attempt_path = local_attempt_path.to_string_lossy().to_string(),
                    sst_file_count = rocks_metadata.sst_files.len(),
                    sequence = rocks_metadata.sequence,
                    "Checkpoint worker: created local checkpoint",
                );

                Ok(rocks_metadata)
            }

            Err(e) => {
                // Build the complete error chain
                let mut error_chain = vec![format!("{:?}", e)];
                let mut source = e.source();
                while let Some(err) = source {
                    error_chain.push(format!("Caused by: {err:?}"));
                    source = err.source();
                }

                let tags = [("result", "error"), ("cause", "local_checkpoint")];
                metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                error!(
                    self.worker_id,
                    local_attempt_path = local_attempt_path.to_string_lossy().to_string(),
                    "Checkpoint worker: local attempt failed: {}",
                    error_chain.join(" -> ")
                );

                Err(anyhow::anyhow!(error_chain.join(" -> ")))
            }
        }
    }

    async fn export_checkpoint_cancellable(
        &self,
        rocks_metadata: &LocalCheckpointInfo,
        previous_metadata: Option<&CheckpointMetadata>,
        cancel_token: Option<&CancellationToken>,
        cancel_cause: Option<&str>,
    ) -> Result<Option<CheckpointInfo>> {
        let local_attempt_path_tag = self.get_local_attempt_path().to_string_lossy().to_string();
        let attempt_type = if previous_metadata.is_some() {
            "incremental"
        } else {
            "full"
        };

        // Get committed consumer and producer offsets from the offset tracker
        // These represent the true recovery points for checkpointing:
        // - consumer_offset: where Kafka would resume consumption after restart
        // - producer_offset: highest offset written to output topic
        let (consumer_offset, producer_offset) = match &self.offset_tracker {
            Some(tracker) => {
                let consumer = tracker.get_committed_offset(&self.partition).unwrap_or(0);
                let producer = tracker.get_producer_offset(&self.partition).unwrap_or(0);
                (consumer, producer)
            }
            None => (0_i64, 0_i64),
        };

        info!(
            self.worker_id,
            local_attempt_path = local_attempt_path_tag,
            attempt_type,
            consumer_offset,
            producer_offset,
            "Checkpoint worker: exporting remote checkpoint",
        );

        match self.exporter.as_ref() {
            Some(exporter) => {
                // Create checkpoint plan
                let plan = plan_checkpoint(
                    &self.get_local_attempt_path(),
                    self.remote_namespace.clone(),
                    self.partition.clone(),
                    self.attempt_timestamp,
                    rocks_metadata.sequence,
                    consumer_offset,
                    producer_offset,
                    previous_metadata,
                )?;

                info!(
                    self.worker_id,
                    local_attempt_path = local_attempt_path_tag,
                    attempt_type,
                    total_files = plan.info.metadata.files.len(),
                    new_files = plan.files_to_upload.len(),
                    reused_files = plan.info.metadata.files.len() - plan.files_to_upload.len(),
                    "Checkpoint worker: plan created"
                );

                // Export checkpoint using the plan with cancellation support
                match exporter
                    .export_checkpoint_with_plan_cancellable(&plan, cancel_token, cancel_cause)
                    .await
                {
                    Ok(()) => {
                        let tags = [("result", "success"), ("export", "success")];
                        metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                        info!(
                            self.worker_id,
                            local_attempt_path = local_attempt_path_tag,
                            remote_path = plan.info.get_remote_attempt_path(),
                            attempt_type,
                            "Checkpoint worker: export successfully"
                        );

                        Ok(Some(plan.info))
                    }

                    Err(e) => {
                        // Cancellation is NOT an error - metrics only (s3_uploader already logged the detail)
                        if e.downcast_ref::<UploadCancelledError>().is_some() {
                            let tags = [("result", "skipped"), ("cause", "cancelled")];
                            metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                        } else {
                            let tags = [("result", "error"), ("cause", "export")];
                            metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                            error!(
                                self.worker_id,
                                local_attempt_path = local_attempt_path_tag,
                                attempt_type,
                                "Checkpoint worker: export failed: {}",
                                e
                            );
                        }

                        Err(e)
                    }
                }
            }

            None => {
                let tags = [("result", "success"), ("export", "skipped")];
                metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                warn!(
                    self.worker_id,
                    local_attempt_path = local_attempt_path_tag,
                    attempt_type,
                    "Checkpoint worker: export skipped: no exporter configured",
                );

                Ok(None)
            }
        }
    }

    // Build local file path associated with this checkpoint attempt
    pub fn get_local_attempt_path(&self) -> PathBuf {
        let checkpoint_id = CheckpointMetadata::generate_id(self.attempt_timestamp);
        self.local_base_dir
            .join(self.partition.topic())
            .join(self.partition.partition_number().to_string())
            .join(checkpoint_id)
    }

    async fn get_directory_size(path: &Path) -> Result<u64> {
        let mut total_size = 0u64;
        let mut stack = vec![path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let mut entries = tokio::fs::read_dir(&current_path)
                .await
                .context("Failed to read directory")?;

            while let Some(entry) = entries.next_entry().await? {
                let entry_path = entry.path();
                if entry_path.is_dir() {
                    stack.push(entry_path);
                } else {
                    let metadata = entry.metadata().await?;
                    total_size += metadata.len();
                }
            }
        }

        Ok(total_size)
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::time::Duration;

    use tempfile::TempDir;

    use super::*;
    use crate::checkpoint::CheckpointConfig;
    use crate::store::{TimestampKey, TimestampMetadata};
    use crate::test_utils::test_helpers::{create_test_dedup_store, create_test_raw_event};

    fn find_local_checkpoint_files(base_dir: &Path) -> Result<Vec<PathBuf>> {
        let mut checkpoint_files = Vec::new();
        let mut stack = vec![base_dir.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let entries = std::fs::read_dir(&current_path)?;

            for entry in entries {
                let entry = entry?;
                let path = entry.path();

                if path.is_file() {
                    checkpoint_files.push(path);
                } else if path.is_dir() {
                    stack.push(path);
                }
            }
        }

        Ok(checkpoint_files)
    }

    #[tokio::test]
    async fn test_worker_local_checkpoint_creates_expected_files() {
        // Create store with test data
        let tmp_store_dir = TempDir::new().unwrap();
        let store = create_test_dedup_store(tmp_store_dir.path(), "test_topic", 0);

        let event = create_test_raw_event();
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store.put_timestamp_record(&key, &metadata).unwrap();

        // Create checkpoint worker
        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        let partition = Partition::new("test_topic".to_string(), 0);
        let attempt_timestamp = Utc::now();

        let worker = CheckpointWorker::new(
            1,
            Path::new(&config.local_checkpoint_dir),
            config.s3_key_prefix.clone(),
            partition.clone(),
            attempt_timestamp,
            None,
            None,
        );

        // Execute checkpoint
        let result = worker.create_checkpoint(&store).await;
        assert!(result.is_ok());

        // Verify checkpoint directory and files exist
        let expected_checkpoint_path = worker.get_local_attempt_path();
        assert!(expected_checkpoint_path.exists());

        let checkpoint_files_found =
            find_local_checkpoint_files(&expected_checkpoint_path).unwrap();
        assert!(!checkpoint_files_found.is_empty());

        // Verify expected RocksDB checkpoint files are present
        assert!(
            checkpoint_files_found
                .iter()
                .any(|p| p.to_string_lossy().ends_with("CURRENT")),
            "Missing CURRENT file"
        );
        assert!(
            checkpoint_files_found
                .iter()
                .any(|p| p.to_string_lossy().contains("MANIFEST")),
            "Missing MANIFEST file"
        );
        assert!(
            checkpoint_files_found
                .iter()
                .any(|p| p.to_string_lossy().contains("OPTIONS")),
            "Missing OPTIONS file"
        );
        assert!(
            checkpoint_files_found
                .iter()
                .any(|p| p.to_string_lossy().ends_with(".sst")),
            "Missing .sst file"
        );
        assert!(
            checkpoint_files_found
                .iter()
                .any(|p| p.to_string_lossy().ends_with(".log")),
            "Missing .log file"
        );
    }
}
