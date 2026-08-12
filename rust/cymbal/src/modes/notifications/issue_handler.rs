use crate::core::{
    error::UnhandledError,
    types::notification::{IssueCreated, IssueReopened, IssueSpiking},
};
use crate::modes::notifications::analytics::{capture_issue_created, capture_issue_reopened};
use crate::modes::notifications::context::NotificationsContext;

pub async fn handle_issue_created(
    context: &NotificationsContext,
    notification: IssueCreated,
) -> Result<(), UnhandledError> {
    context
        .issue_lifecycle_workflow_starters
        .start_created(&notification)
        .await?;

    let sentry_integration = notification
        .issue
        .event_properties
        .properties()
        .contains_key("$sentry_event_id");
    capture_issue_created(
        notification.meta.team_id,
        notification.issue.issue_id,
        sentry_integration,
    );
    Ok(())
}

pub async fn handle_issue_reopened(
    context: &NotificationsContext,
    notification: IssueReopened,
) -> Result<(), UnhandledError> {
    context
        .issue_lifecycle_workflow_starters
        .start_reopened(&notification)
        .await?;

    capture_issue_reopened(notification.meta.team_id, notification.issue.issue_id);
    Ok(())
}

pub async fn handle_issue_spiking(
    context: &NotificationsContext,
    notification: IssueSpiking,
) -> Result<(), UnhandledError> {
    context
        .issue_lifecycle_workflow_starters
        .start_spiking(&notification)
        .await
}
