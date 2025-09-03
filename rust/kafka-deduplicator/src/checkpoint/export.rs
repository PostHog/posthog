use anyhow::{Context, Result};
use metrics;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;
use tokio::time;
use tracing::{debug, error, info, warn};

use super::{CheckpointConfig, CheckpointUploader};
use crate::kafka::types::Partition;
use crate::rocksdb::deduplication_store::DeduplicationStore;

const CHECKPOINT_LAST_TIMESTAMP_GAUGE: &str = "checkpoint_last_timestamp";
const CHECKPOINT_DURATION_HISTOGRAM: &str = "checkpoint_duration_seconds";
const CHECKPOINT_SIZE_HISTOGRAM: &str = "checkpoint_size_bytes";
const CHECKPOINT_UPLOAD_DURATION_HISTOGRAM: &str = "checkpoint_upload_duration_seconds";
const CHECKPOINT_ERRORS_COUNTER: &str = "checkpoint_errors_total";

pub const CHECKPOINT_NAME_PREFIX: &str = "chkpt";

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

    /// Start the checkpoint loop that triggers checkpoints based on the configured interval
    // TBD: might remove this and integrate with CheckpointManager's flush loop instead
    pub async fn start_checkpoint_loop(&self, store: Arc<DeduplicationStore>) {
        let mut interval = time::interval(self.config.checkpoint_interval);

        info!(
            "Starting checkpoint loop with interval: {:?}",
            self.config.checkpoint_interval
        );

        loop {
            interval.tick().await;

            if let Err(e) = self.maybe_checkpoint(&store).await {
                error!("Checkpoint failed: {}", e);
                metrics::counter!(CHECKPOINT_ERRORS_COUNTER).increment(1);
            }
        }
    }

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

        result.map(|_| true)
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

    async fn perform_checkpoint(&self, store: &DeduplicationStore) -> Result<()> {
        let start_time = Instant::now();
        let partition: Partition =
            Partition::new(store.get_topic().to_string(), store.get_partition());

        info!("Starting checkpoint creation");

        // Create checkpoint directory with timestamp (microseconds for uniqueness)
        // and ensure the checkpoint name is unique and lexicographically sortable
        let checkpoint_timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("Failed to get current timestamp")?
            .as_micros();
        let checkpoint_name = self.build_checkpoint_name(&partition, checkpoint_timestamp);
        let local_checkpoint_path =
            PathBuf::from(&self.config.local_checkpoint_dir).join(&checkpoint_name);

        // Ensure local checkpoint directory exists
        tokio::fs::create_dir_all(&self.config.local_checkpoint_dir)
            .await
            .context("Failed to create local checkpoint directory")?;

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

        let checkpoint_duration = start_time.elapsed();
        metrics::histogram!(CHECKPOINT_DURATION_HISTOGRAM)
            .record(checkpoint_duration.as_secs_f64());

        // Get checkpoint size
        let checkpoint_size = self.get_directory_size(&local_checkpoint_path).await?;
        metrics::histogram!(CHECKPOINT_SIZE_HISTOGRAM).record(checkpoint_size as f64);

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

        // Cleanup old local checkpoints
        self.cleanup_local_checkpoints().await?;

        info!("Checkpoint {} completed successfully", checkpoint_name);
        Ok(())
    }

    async fn get_directory_size(&self, path: &Path) -> Result<u64> {
        let mut total_size = 0u64;
        let mut stack = vec![path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let mut entries = tokio::fs::read_dir(&current_path)
                .await
                .with_context(|| format!("Failed to read directory: {current_path:?}"))?;

            while let Some(entry) = entries.next_entry().await? {
                let path = entry.path();
                let metadata = entry.metadata().await?;

                if metadata.is_dir() {
                    stack.push(path);
                } else {
                    total_size += metadata.len();
                }
            }
        }

        Ok(total_size)
    }

    async fn cleanup_local_checkpoints(&self) -> Result<()> {
        let checkpoint_dir = PathBuf::from(&self.config.local_checkpoint_dir);

        if !checkpoint_dir.exists() {
            return Ok(());
        }

        let mut entries = tokio::fs::read_dir(&checkpoint_dir)
            .await
            .context("Failed to read checkpoint directory")?;

        let mut checkpoint_dirs = Vec::new();

        while let Some(entry) = entries.next_entry().await? {
            let path = entry.path();
            if path.is_dir() {
                if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                    if name.starts_with(CHECKPOINT_NAME_PREFIX) {
                        checkpoint_dirs.push(path);
                    }
                }
            }
        }

        // Sort by name (which includes timestamp)
        checkpoint_dirs.sort();

        if checkpoint_dirs.len() <= self.config.max_local_checkpoints {
            return Ok(());
        }

        let dirs_to_remove = checkpoint_dirs.len() - self.config.max_local_checkpoints;

        for dir in checkpoint_dirs.into_iter().take(dirs_to_remove) {
            if let Err(e) = tokio::fs::remove_dir_all(&dir).await {
                error!("Failed to remove old checkpoint directory {:?}: {}", dir, e);
                // Continue with other removals
            } else {
                info!("Removed old checkpoint directory: {:?}", dir);
            }
        }

        Ok(())
    }

    // TODO(eli): discussed breaking this in to path-like elements but so far
    // I'm leaning towards keeping it a single directory name. It's sortable,
    // simple to work with, and maintains a 1:1 mapping between local paths under
    // base dir and S3 snapshot paths under bucket key prefix. Can revisit if needed
    fn build_checkpoint_name(&self, partition: &Partition, checkpoint_timestamp: u128) -> String {
        format!(
            "{}_{}_{}_{:018}",
            CHECKPOINT_NAME_PREFIX,
            partition.topic(),
            partition.partition_number(),
            checkpoint_timestamp
        )
    }
}
