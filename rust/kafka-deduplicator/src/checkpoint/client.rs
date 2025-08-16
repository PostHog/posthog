use anyhow::Result;
use async_trait::async_trait;
use std::path::Path;

use super::metadata::{CheckpointInfo, CheckpointMetadata};

/// Trait for discovering and downloading checkpoints from remote storage
#[async_trait]
pub trait CheckpointClient: Send + Sync + std::fmt::Debug + 'static + Clone {
    /// List all checkpoint metadata files in remote storage
    async fn list_checkpoint_metadata(
        &self,
        topic: &str,
        partition: i32,
    ) -> Result<Vec<CheckpointInfo>>;

    /// Download a specific checkpoint to local directory
    async fn download_checkpoint(
        &self,
        checkpoint_info: &CheckpointInfo,
        local_path: &Path,
    ) -> Result<()>;

    /// Get checkpoint metadata by key
    async fn get_checkpoint_metadata(&self, metadata_key: &str) -> Result<CheckpointMetadata>;

    /// Check if a checkpoint exists
    async fn checkpoint_exists(&self, checkpoint_info: &CheckpointInfo) -> Result<bool>;

    /// Check if the client is available/configured
    async fn is_available(&self) -> bool;
}
