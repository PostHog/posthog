use std::path::{Path, PathBuf};

use super::{CheckpointDownloader, CheckpointMetadata};

use anyhow::{Context, Result};
use tracing::{error, info};

#[derive(Debug)]
pub struct CheckpointImporter {
    downloader: Box<dyn CheckpointDownloader>,
}

impl CheckpointImporter {
    pub fn new(downloader: Box<dyn CheckpointDownloader>) -> Self {
        Self { downloader }
    }

    /// This is the one-stop entry point for DR checkpoint import.
    /// Given the following inputs:
    /// - local_base_path: a base path for temporary downloads (not scoped to topic/partition)
    /// - topic: the topic to import checkpoints for
    /// - partition: the partition number to import checkpoints for
    /// - import_limit: the maximum number of recent checkpoints to attempt to import as fallbacks
    ///
    /// This method will:
    /// 1. Fetch checkpoint metadata.json files from the most recent N checkpoints for the topic+partition
    /// 2. For each metadata file (newest to oldest), attempt to download all tracked files to local directory
    ///    of the form <local_base_path>/<topic>/<partition>/<checkpoint_id>/ (assumed to be a temp dir)
    /// 3. If a checkpoint import fails, fall back to the next most recent (up to import_limit) before giving up
    /// 4. If successful, return the final local path to the most recent successful checkpoint was imported to
    pub async fn import_checkpoint_for_topic_partition(
        &self,
        local_base_path: &Path,
        topic: &str,
        partition_number: i32,
        import_limit: usize,
    ) -> Result<PathBuf> {
        let mut checkpoint_metadata = self
            .fetch_checkpoint_metadata(topic, partition_number)
            .await?;

        info!(
            "Found {} checkpoint attempts for topic:{} partition:{}",
            checkpoint_metadata.len(),
            topic,
            partition_number
        );

        // Slice to at most the most-recent N checkpoints
        // we'll attempt to import according to import_limit
        checkpoint_metadata.truncate(import_limit);
        info!("Attempting recovery from the most recent {} checkpoints for topic:{topic} partition:{partition_number}",
            checkpoint_metadata.len());

        // checkpoints iterated in order of recency; we keep the first good one we fetch
        for attempt in checkpoint_metadata {
            let local_attempt_path = local_base_path.join(attempt.get_attempt_path());
            let attempt_tag = attempt
                .to_json()
                .unwrap_or(local_attempt_path.to_string_lossy().to_string());
            info!(
                checkpoint = attempt_tag,
                "Attempting to import checkpoint to local directory"
            );

            match self
                .fetch_checkpoint_files(&attempt, &local_attempt_path)
                .await
            {
                Ok(_) => {
                    info!(
                        checkpoint = attempt_tag,
                        "Successfully imported checkpoint to local directory"
                    );
                    return Ok(local_attempt_path);
                }
                Err(e) => {
                    error!(
                        checkpont = attempt_tag,
                        error = e.to_string(),
                        "Failed to import checkpoint files "
                    );
                    if local_attempt_path.exists() {
                        match tokio::fs::remove_dir_all(&local_attempt_path).await {
                            Ok(_) => {
                                info!(
                                    checkpoint = attempt_tag,
                                    "Removed local directory after checkpoint import failure"
                                );
                            }
                            Err(e) => {
                                error!(
                                    checkpoint = attempt_tag,
                                    error = e.to_string(),
                                    "Failed to remove local directory after checkpoint import failure");
                            }
                        }
                    }
                    continue;
                }
            }
        }

        let err_msg = format!(
            "No usable checkpoints identified in recovery window for topic:{topic} partition:{partition_number}"
        );
        error!(err_msg);
        Err(anyhow::anyhow!(err_msg))
    }

    pub async fn fetch_checkpoint_metadata(
        &self,
        topic: &str,
        partition_number: i32,
    ) -> Result<Vec<CheckpointMetadata>> {
        let remote_metadata_files = self
            .downloader
            .list_recent_checkpoints(topic, partition_number)
            .await
            .context("In fetch_checkpoint_metadata")?;

        let mut fetched_metadata_files = Vec::new();
        for remote_key in remote_metadata_files {
            match self.downloader.download_file(&remote_key).await {
                Ok(content) => match CheckpointMetadata::from_json_bytes(&content) {
                    Ok(metadata) => {
                        fetched_metadata_files.push(metadata);
                    }
                    Err(e) => {
                        error!("Failed to parse metadata from file bytes: {remote_key}: {e}");
                    }
                },
                Err(e) => {
                    error!("Failed to download metadata file: {remote_key}: {e}");
                }
            }
        }

        if fetched_metadata_files.is_empty() {
            return Err(anyhow::anyhow!("No checkpoint metadata files downloaded successfully for topic:{topic} partition:{partition_number}"));
        }

        Ok(fetched_metadata_files)
    }

    pub async fn fetch_checkpoint_files(
        &self,
        checkpoint_metadata: &CheckpointMetadata,
        local_attempt_path: &Path,
    ) -> Result<()> {
        let target_files = checkpoint_metadata
            .files
            .iter()
            .map(|f| f.remote_filepath.clone())
            .collect::<Vec<_>>();

        info!(
            metadata = checkpoint_metadata.get_metadata_filepath(),
            file_count = checkpoint_metadata.files.len(),
            "Fetching checkpoint files from metadata tracking list",
        );

        match self
            .downloader
            .download_files(&target_files, local_attempt_path)
            .await
        {
            Ok(_) => {
                info!(
                    "Successfully downloaded {} checkpoint files to: {local_attempt_path:?}",
                    target_files.len()
                );
                Ok(())
            }
            Err(e) => {
                error!("Failed to download checkpoint files to: {local_attempt_path:?}: {e}");
                Err(e)
            }
        }
    }

    pub async fn is_available(&self) -> bool {
        self.downloader.is_available().await
    }
}
