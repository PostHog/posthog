use anyhow::Result;
use async_trait::async_trait;
use tokio_util::sync::CancellationToken;

use super::CheckpointPlan;

#[async_trait]
pub trait CheckpointUploader: Send + Sync + std::fmt::Debug {
    async fn upload_checkpoint_with_plan(&self, plan: &CheckpointPlan) -> Result<Vec<String>> {
        self.upload_checkpoint_with_plan_cancellable(plan, None)
            .await
    }

    /// On cancellation, aborts any in-progress multipart uploads to prevent ghost parts.
    async fn upload_checkpoint_with_plan_cancellable(
        &self,
        plan: &CheckpointPlan,
        cancel_token: Option<&CancellationToken>,
    ) -> Result<Vec<String>>;

    async fn is_available(&self) -> bool;
}
