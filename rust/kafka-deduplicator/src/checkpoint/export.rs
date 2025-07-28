use anyhow::{Context, Result};
use metrics;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;
use tokio::time;
use tracing::{debug, error, info, warn};

use super::{CheckpointConfig, CheckpointUploader};
use crate::rocksdb::deduplication_store::DeduplicationStore;

const CHECKPOINT_LAST_TIMESTAMP_GAUGE: &str = "checkpoint_last_timestamp";
const CHECKPOINT_DURATION_HISTOGRAM: &str = "checkpoint_duration_seconds";
const CHECKPOINT_SIZE_HISTOGRAM: &str = "checkpoint_size_bytes";
const CHECKPOINT_UPLOAD_DURATION_HISTOGRAM: &str = "checkpoint_upload_duration_seconds";
const CHECKPOINT_ERRORS_COUNTER: &str = "checkpoint_errors_total";

#[derive(Debug)]
pub struct CheckpointExporter {
    config: CheckpointConfig,
    uploader: Box<dyn CheckpointUploader>,
    last_checkpoint: Arc<Mutex<Option<Instant>>>,
    checkpoint_counter: Arc<Mutex<u32>>,
    is_checkpointing: Arc<Mutex<bool>>,
}

impl CheckpointExporter {
    pub fn new(config: CheckpointConfig, uploader: Box<dyn CheckpointUploader>) -> Self {
        Self {
            config,
            uploader,
            last_checkpoint: Arc::new(Mutex::new(None)),
            checkpoint_counter: Arc::new(Mutex::new(0)),
            is_checkpointing: Arc::new(Mutex::new(false)),
        }
    }

    /// Start the checkpoint loop that triggers checkpoints based on the configured interval
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
        // Check if checkpoint is already in progress
        {
            let is_checkpointing = self.is_checkpointing.lock().await;
            if *is_checkpointing {
                debug!("Checkpoint already in progress, skipping");
                return Ok(false);
            }
        }

        // Set checkpoint in progress flag
        {
            let mut is_checkpointing = self.is_checkpointing.lock().await;
            *is_checkpointing = true;
        }

        let result = self.perform_checkpoint(store).await;

        // Clear checkpoint in progress flag
        {
            let mut is_checkpointing = self.is_checkpointing.lock().await;
            *is_checkpointing = false;
        }

        result.map(|_| true)
    }

    async fn perform_checkpoint(&self, store: &DeduplicationStore) -> Result<()> {
        let start_time = Instant::now();

        info!("Starting checkpoint creation");

        // Create checkpoint directory with timestamp (microseconds for uniqueness)
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("Failed to get current timestamp")?
            .as_micros();

        let checkpoint_name = format!("checkpoint_{}", timestamp);
        let local_checkpoint_path =
            PathBuf::from(&self.config.local_checkpoint_dir).join(&checkpoint_name);

        // Ensure local checkpoint directory exists
        tokio::fs::create_dir_all(&self.config.local_checkpoint_dir)
            .await
            .context("Failed to create local checkpoint directory")?;

        // Create checkpoint with SST file tracking
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
            let mut last_checkpoint = self.last_checkpoint.lock().await;
            *last_checkpoint = Some(Instant::now());
            metrics::gauge!(CHECKPOINT_LAST_TIMESTAMP_GAUGE).set((timestamp / 1_000_000) as f64);
        }

        // Determine if this should be a full upload or incremental
        let mut counter = self.checkpoint_counter.lock().await;
        *counter += 1;
        let is_full_upload = *counter % self.config.full_upload_interval == 0;

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
            warn!("Uploader not available, checkpoint will remain local only");
        }

        // Cleanup old local checkpoints
        self.cleanup_local_checkpoints().await?;

        // Cleanup old remote checkpoints if this was a full upload
        if is_full_upload && self.uploader.is_available().await {
            if let Err(e) = self
                .uploader
                .cleanup_old_checkpoints(self.config.max_local_checkpoints)
                .await
            {
                error!("Failed to cleanup old remote checkpoints: {}", e);
                // Don't fail the checkpoint for cleanup errors
            }
        }

        info!("Checkpoint {} completed successfully", checkpoint_name);
        Ok(())
    }

    async fn get_directory_size(&self, path: &Path) -> Result<u64> {
        let mut total_size = 0u64;
        let mut stack = vec![path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let mut entries = tokio::fs::read_dir(&current_path)
                .await
                .with_context(|| format!("Failed to read directory: {:?}", current_path))?;

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
                    if name.starts_with("checkpoint_") {
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

    /// Get the timestamp of the last checkpoint
    pub async fn last_checkpoint_timestamp(&self) -> Option<Instant> {
        *self.last_checkpoint.lock().await
    }

    /// Check if a checkpoint is currently in progress
    pub async fn is_checkpointing(&self) -> bool {
        *self.is_checkpointing.lock().await
    }
}
