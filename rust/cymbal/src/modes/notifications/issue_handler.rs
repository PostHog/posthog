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
    let team_id = notification.meta.team_id;
    let issue_id = notification.issue.issue_id;
    let sentry_integration = notification
        .issue
        .event_properties
        .properties()
        .contains_key("$sentry_event_id");

    let decision = context.issue_created_limiter.decide(team_id).await;
    if decision.is_limited() {
        // The issue itself was still created, so keep counting it. Only the
        // workflow, and with it the embedding and the alert, was cut.
        capture_issue_created(team_id, issue_id, sentry_integration, true);
        return Ok(());
    }

    let start = context
        .issue_lifecycle_workflow_starters
        .start_created(&notification)
        .await?;
    context
        .issue_created_limiter
        .settle(team_id, decision, start)
        .await;

    capture_issue_created(team_id, issue_id, sentry_integration, false);
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
        .await?;
    Ok(())
}
