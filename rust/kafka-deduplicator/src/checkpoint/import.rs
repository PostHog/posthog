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
            match self.fetch_checkpoint_files(&attempt, local_base_path).await {
                Ok(local_attempt_path) => {
                    // TODO: stat this too
                    info!("Successfully imported checkpoint to: {local_attempt_path:?}");
                    return Ok(local_attempt_path);
                }
                Err(e) => {
                    // TODO: stat this too
                    error!("Failed to import checkpoint files for metadata: {attempt:?} got: {e}");
                    continue;
                }
            }
        }

        Err(anyhow::anyhow!(
            "No usable checkpoints identified in search window for topic:{} partition:{}",
            topic,
            partition_number
        ))
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
        local_base_path: &Path,
    ) -> Result<PathBuf> {
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

        // append <topic>/<partition>/<checkpoint_id>/ to the local base path
        let local_attempt_path = local_base_path.join(checkpoint_metadata.get_attempt_path());
        match self
            .downloader
            .download_files(&target_files, &local_attempt_path)
            .await
        {
            Ok(_) => {
                info!(
                    "Successfully downloaded {} checkpoint files to: {local_attempt_path:?}",
                    target_files.len()
                );
                Ok(local_attempt_path)
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
