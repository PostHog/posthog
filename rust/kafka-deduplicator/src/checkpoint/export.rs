use anyhow::{Context, Result};
use metrics;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;
use tracing::{debug, error, info, warn};

use super::{CheckpointConfig, CheckpointUploader};
use crate::kafka::types::Partition;
use crate::rocksdb::deduplication_store::DeduplicationStore;

const CHECKPOINT_LAST_TIMESTAMP_GAUGE: &str = "checkpoint_last_timestamp";
const CHECKPOINT_UPLOAD_DURATION_HISTOGRAM: &str = "checkpoint_upload_duration_seconds";
const CHECKPOINT_ERRORS_COUNTER: &str = "checkpoint_errors_total";

#[derive(Debug)]
pub struct CheckpointExporter {
    config: CheckpointConfig,
    uploader: Box<dyn CheckpointUploader>,
    last_checkpoints: Arc<Mutex<HashMap<Partition, Instant>>>,
    checkpoint_counters: Arc<Mutex<HashMap<Partition, u32>>>,
    is_checkpointing: Arc<Mutex<HashSet<Partition>>>,
}

impl CheckpointExporter {
    pub fn new(config: CheckpointConfig, uploader: Box<dyn CheckpointUploader>) -> Self {
        Self {
            config,
            uploader,
            last_checkpoints: Arc::new(Mutex::new(HashMap::new())),
            checkpoint_counters: Arc::new(Mutex::new(HashMap::new())),
            is_checkpointing: Arc::new(Mutex::new(HashSet::new())),
        }
    }

    // TODO(eli): move this management and coordination plumbing to checkpoint manager!

    /// Trigger a checkpoint if one is not already in progress
    pub async fn maybe_checkpoint(&self, store: &DeduplicationStore) -> Result<bool> {
        // Try to acquire the checkpoint lock - if already locked, skip
        let partition = Partition::new(store.get_topic().to_string(), store.get_partition());

        // Attempt to acquire the checkpoint lock or bail if already in flight
        {
            let mut is_checkpointing = self.is_checkpointing.lock().await;
            if is_checkpointing.contains(&partition) {
                debug!("Checkpoint already in progress, skipping");
                return Ok(false);
            }
            is_checkpointing.insert(partition.clone());
        }

        // if we got here, the checkpoint is in progress and locked now...

        // TODO(eli): perhaps wrap with panic::catch_unwind here for extra safety unlocking?
        let result = self.perform_checkpoint(store).await;

        // Atomically clear the checkpoint in progress flag
        {
            let mut is_checkpointing = self.is_checkpointing.lock().await;
            is_checkpointing.remove(&partition);
        }

        if let Err(e) = result {
            let topic_name = store.get_topic().to_string();
            error!(
                "Checkpoint for store {}:{} failed: {}",
                topic_name,
                store.get_partition(),
                e
            );
            metrics::counter!(CHECKPOINT_ERRORS_COUNTER, "topic" => topic_name).increment(1);
            return Err(e);
        }

        Ok(true)
    }

    /// Get the timestamp of the last checkpoint
    pub async fn last_checkpoint_timestamp(&self, partition: &Partition) -> Option<Instant> {
        let last_checkpoints = self.last_checkpoints.lock().await;
        last_checkpoints.get(partition).cloned()
    }

    /// Check if a checkpoint is currently in progress
    pub async fn is_checkpointing(&self, partition: &Partition) -> bool {
        let statuses = self.is_checkpointing.lock().await;
        statuses.contains(partition)
    }

    // returns the remote key prefix for this checkpoint or an error
    pub async fn export_checkpoint(
        &self,
        local_checkpoint_path: &Path,
        checkpoint_name: &str,
        store: &DeduplicationStore,
    ) -> Result<String> {
        let start_time = Instant::now();

        // Determine if this should be a full upload or incremental
        let current_part_counter: u32;
        {
            // TODO(eli): the previous checkpoint metadata should contain the
            //            associated counter so we don't restart every redeploy
            let mut counters = self.checkpoint_counters.lock().await;
            let result = counters.get(&partition).unwrap_or(&0_u32);
            current_part_counter = *result;
            counters.insert(partition.clone(), current_part_counter + 1);
        }
        let is_full_upload = current_part_counter % self.config.full_upload_interval == 0;

        // Create checkpoint with SST file tracking
        // TODO(eli): add is_full_upload flag to create_checkpoint_with_metadata
        let sst_files = store
            .create_checkpoint_with_metadata(&local_checkpoint_path)
            .context("Failed to create checkpoint")?;

        info!(
            "Created checkpoint {} with {} SST files, size: {} bytes, duration: {:?}",
            checkpoint_name,
            sst_files.len(),
            checkpoint_size,
            checkpoint_duration
        );

        // Update last checkpoint timestamp
        {
            let mut last_checkpoints = self.last_checkpoints.lock().await;
            last_checkpoints.insert(partition.clone(), Instant::now());
            // TODO(eli): facet (tag) by topic/partition? track Instant here instead of start time?
            metrics::gauge!(CHECKPOINT_LAST_TIMESTAMP_GAUGE)
                .set((checkpoint_timestamp / 1_000_000) as f64);
        }

        // Upload to remote storage in background
        if self.uploader.is_available().await {
            let upload_start = Instant::now();

            let s3_key_prefix = if is_full_upload {
                format!("{}/full/{}", self.config.s3_key_prefix, checkpoint_name)
            } else {
                format!(
                    "{}/incremental/{}",
                    self.config.s3_key_prefix, checkpoint_name
                )
            };

            match self
                .uploader
                .upload_checkpoint_dir(&local_checkpoint_path, &s3_key_prefix)
                .await
            {
                Ok(uploaded_files) => {
                    let upload_duration = upload_start.elapsed();
                    metrics::histogram!(CHECKPOINT_UPLOAD_DURATION_HISTOGRAM)
                        .record(upload_duration.as_secs_f64());

                    info!(
                        "Uploaded checkpoint {} ({} type) with {} files in {:?}",
                        checkpoint_name,
                        if is_full_upload {
                            "full"
                        } else {
                            "incremental"
                        },
                        uploaded_files.len(),
                        upload_duration
                    );
                }
                Err(e) => {
                    error!("Failed to upload checkpoint {}: {}", checkpoint_name, e);
                    return Err(e);
                }
            }
        } else {
            // TODO(eli): add metric emission for this, it's serious!
            warn!("Uploader not available, checkpoint will remain local only");
        }

        // TODO(eli): MOVE TO CHECKPOINT MANAGER
        // Cleanup old local checkpoints
        self.cleanup_local_checkpoints().await?;

        info!("Checkpoint {} completed successfully", checkpoint_name);
        Ok(remote_key_prefix)
    }
}
