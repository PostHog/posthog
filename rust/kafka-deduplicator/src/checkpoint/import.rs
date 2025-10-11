use std::path::Path;

use super::{metadata::CheckpointMetadata, target::CheckpointTarget, CheckpointDownloader};

use anyhow::{Context, Result};

#[derive(Debug)]
pub struct CheckpointImporter {
    downloader: Box<dyn CheckpointDownloader>,
}

// TODO(eli): temporary - remove in follow-on as we wire up conditional checkpoint import on startup
#[allow(dead_code)]
/// Trait for discovering and downloading checkpoints from remote storage
impl CheckpointImporter {
    pub fn new(downloader: Box<dyn CheckpointDownloader>) -> Self {
        Self { downloader }
    }

    /// Fetch and hydrate CheckpointMetadata objects for all (or most-recent N) remote metadata files
    /// associated with the given CheckpointTarget. Arguments:
    /// - target: an *unscoped* (no attempt timestamp) CheckpointTarget representing this topic & partition
    /// - local_base_dir: the local temp base directory we will download checkpoint files to in later steps
    /// - limit: optional - if set, the most recent N metadata files to fetch
    async fn fetch_checkpoint_metadata(
        &self,
        target: &CheckpointTarget,
        local_base_dir: &Path,
        limit: Option<usize>,
    ) -> Result<Vec<CheckpointMetadata>> {
        let remote_meta_path = target.remote_metadata_path();
        let remote_meta_files = self
            .downloader
            .list_checkpoint_metadata(&remote_meta_path)
            .await?;

        let selected_files = remote_meta_files
            .iter()
            .take(limit.unwrap_or(remote_meta_files.len()));

        let mut metadata_objects = Vec::with_capacity(selected_files.len());
        for remote_meta_file in selected_files {
            let payload = self
                .downloader
                .download_metadata_file(remote_meta_file)
                .await?;

            let mut metadata = CheckpointMetadata::from_payload(&payload)
                .context("In CheckpointImporter::fetch_checkpoint_metadata")?;
            metadata.target.with_local_base_dir(local_base_dir);

            metadata_objects.push(metadata);
        }

        Ok(metadata_objects)
    }

    /// Download a specific checkpoint attempt to local filesystem as specified by the
    /// given CheckpointMetadata. Returns the list of downloaded files without path prefixes
    /// just as they were originally recorded in the CheckpointMetadata during export
    async fn fetch_checkpoint(&self, metadata: &CheckpointMetadata) -> Result<Vec<String>> {
        let remote_attempt_path = metadata
            .target
            .remote_attempt_path()
            .context("In CheckpointImporter::fetch_checkpoint")?;
        let local_attempt_path = metadata
            .target
            .local_attempt_path()
            .context("In CheckpointImporter::fetch_checkpoint")?;

        self.downloader
            .download_checkpoint(&remote_attempt_path, &local_attempt_path)
            .await
    }

    /// Given a particular checkpoint attempt metadata, check if the remote checkpoint files exist
    async fn checkpoint_exists(&self, metadata: &CheckpointMetadata) -> Result<bool> {
        let remote_attempt_path = metadata
            .target
            .remote_attempt_path()
            .context("In CheckpointImporter::checkpoint_exists")?;
        self.downloader
            .checkpoint_exists(&remote_attempt_path)
            .await
    }

    /// Check if the client is available/configured
    async fn is_available(&self) -> bool {
        self.downloader.is_available().await
    }
}
