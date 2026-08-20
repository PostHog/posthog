use crate::core::{
    error::UnhandledError,
    types::notification::{IssueCreated, IssueReopened, IssueSpiking},
};
use crate::modes::notifications::analytics::{capture_issue_created, capture_issue_reopened};
use crate::modes::notifications::context::NotificationsContext;

const ISSUE_CREATED: &str = "issue_created";
const ISSUE_REOPENED: &str = "issue_reopened";
const ISSUE_SPIKING: &str = "issue_spiking";

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

    let decision = context
        .lifecycle_limiter
        .decide(team_id, ISSUE_CREATED)
        .await;
    if decision.is_limited() {
        // The issue itself was still created, so keep counting it. Only the
        // lifecycle workflow, and with it the embedding and the alert, was cut.
        capture_issue_created(team_id, issue_id, sentry_integration, true);
        return Ok(());
    }

    let start = context
        .issue_lifecycle_workflow_starters
        .start_created(&notification)
        .await?;
    context
        .lifecycle_limiter
        .settle(team_id, ISSUE_CREATED, decision, start)
        .await;

    capture_issue_created(team_id, issue_id, sentry_integration, false);
    Ok(())
}

pub async fn handle_issue_reopened(
    context: &NotificationsContext,
    notification: IssueReopened,
) -> Result<(), UnhandledError> {
    let team_id = notification.meta.team_id;
    let issue_id = notification.issue.issue_id;

    let decision = context
        .lifecycle_limiter
        .decide(team_id, ISSUE_REOPENED)
        .await;
    if decision.is_limited() {
        capture_issue_reopened(team_id, issue_id, true);
        return Ok(());
    }

    let start = context
        .issue_lifecycle_workflow_starters
        .start_reopened(&notification)
        .await?;
    context
        .lifecycle_limiter
        .settle(team_id, ISSUE_REOPENED, decision, start)
        .await;

    capture_issue_reopened(team_id, issue_id, false);
    Ok(())
}

pub async fn handle_issue_spiking(
    context: &NotificationsContext,
    notification: IssueSpiking,
) -> Result<(), UnhandledError> {
    let team_id = notification.meta.team_id;

    let decision = context
        .lifecycle_limiter
        .decide(team_id, ISSUE_SPIKING)
        .await;
    if decision.is_limited() {
        return Ok(());
    }

    let start = context
        .issue_lifecycle_workflow_starters
        .start_spiking(&notification)
        .await?;
    context
        .lifecycle_limiter
        .settle(team_id, ISSUE_SPIKING, decision, start)
        .await;

    Ok(())
}
