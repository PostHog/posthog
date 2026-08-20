use std::sync::Arc;

use crate::core::error::UnhandledError;
use crate::modes::notifications::config::NotificationsConfig;
use crate::modes::notifications::rate_limit::LifecycleRateLimiter;
use crate::modes::notifications::temporal::IssueLifecycleWorkflowStarters;

#[derive(Clone)]
pub struct NotificationsContext {
    pub issue_lifecycle_workflow_starters: IssueLifecycleWorkflowStarters,
    pub lifecycle_limiter: Arc<LifecycleRateLimiter>,
}

impl NotificationsContext {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        Ok(Self {
            issue_lifecycle_workflow_starters: IssueLifecycleWorkflowStarters::from_config(config)
                .await?,
            lifecycle_limiter: Arc::new(LifecycleRateLimiter::from_config(config).await?),
        })
    }
}
