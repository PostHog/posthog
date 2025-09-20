use anyhow::Result;
use async_trait::async_trait;
use std::path::Path;

/// Trait for uploading checkpoints to remote storage
#[async_trait]
pub trait CheckpointUploader: Send + Sync + std::fmt::Debug {
    /// Upload a directory to remote storage recursively
    async fn upload_checkpoint_dir(
        &self,
        local_path: &Path,
        remote_key_prefix: &str,
    ) -> Result<Vec<String>>;

    /// Check if the uploader is available/configured
    async fn is_available(&self) -> bool;
}
