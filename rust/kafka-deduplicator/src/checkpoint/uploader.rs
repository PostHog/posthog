use anyhow::Result;
use async_trait::async_trait;

use super::CheckpointPlan;

/// Trait for uploading checkpoints to remote storage
#[async_trait]
pub trait CheckpointUploader: Send + Sync + std::fmt::Debug {
    /// Upload checkpoint using a plan (specific files + metadata)
    async fn upload_checkpoint_with_plan(&self, plan: &CheckpointPlan) -> Result<Vec<String>>;

    /// Check if the uploader is available/configured
    async fn is_available(&self) -> bool;
}
