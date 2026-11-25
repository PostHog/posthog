use std::sync::Arc;

use crate::core::error::UnhandledError;
use crate::modes::notifications::config::NotificationsConfig;
use crate::modes::notifications::issue_changes::SpikeChangeWriter;
use crate::modes::notifications::rate_limit::IssueCreatedRateLimiter;
use crate::modes::notifications::temporal::IssueLifecycleWorkflowStarters;

#[derive(Clone)]
pub struct NotificationsContext {
    pub issue_lifecycle_workflow_starters: IssueLifecycleWorkflowStarters,
    pub issue_created_limiter: Arc<IssueCreatedRateLimiter>,
    pub spike_change_writer: Option<SpikeChangeWriter>,
}

impl NotificationsContext {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        Ok(Self {
            issue_lifecycle_workflow_starters: IssueLifecycleWorkflowStarters::from_config(config)
                .await?,
            issue_created_limiter: Arc::new(IssueCreatedRateLimiter::from_config(config).await?),
            spike_change_writer: SpikeChangeWriter::from_config(config)?,
        })
    }
}
