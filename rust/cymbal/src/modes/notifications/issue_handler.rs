use common_temporal::StartWorkflowOutcome;
use std::time::Duration;

use tracing::{error, warn};

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

    if !context.issue_created_limiter.admit(team_id).await {
        // The issue was still created, so it still counts. Only the workflow,
        // and with it the embedding and the alert, was cut.
        capture_issue_created(team_id, issue_id, sentry_integration, true);
        return Ok(());
    }

    let outcome = context
        .issue_lifecycle_workflow_starters
        .start_created(&notification)
        .await?;

    // A replayed notification carries the same workflow id, so this start bought
    // nothing. Hand the token back rather than let redelivery spend the team's
    // budget on work Temporal is already doing.
    if matches!(outcome, StartWorkflowOutcome::Existing { .. }) {
        context.issue_created_limiter.refund(team_id).await;
    }

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

const RECORD_RETRY_BUDGET: Duration = Duration::from_secs(30);

pub async fn handle_issue_spiking(
    context: &NotificationsContext,
    notification: IssueSpiking,
) -> Result<(), UnhandledError> {
    if let Some(writer) = &context.spike_change_writer {
        // Absorb a database blip here: an error restarts the consumer, which pauses every lifecycle
        // notification behind this one. The budget stays under the pod's shutdown grace period.
        let give_up_at = tokio::time::Instant::now() + RECORD_RETRY_BUDGET;
        let mut delay = Duration::from_millis(250);
        loop {
            match writer.record(&notification).await {
                Ok(()) => break,
                Err(error) if tokio::time::Instant::now() + delay < give_up_at => {
                    warn!(
                        notification_id = %notification.meta.notification_id,
                        error = %error,
                        "Retrying spiking change"
                    );
                    tokio::time::sleep(delay).await;
                    delay = (delay * 2).min(Duration::from_secs(5));
                }
                Err(error) => {
                    error!(
                        team_id = notification.meta.team_id,
                        notification_id = %notification.meta.notification_id,
                        error = %error,
                        "Failed to record spiking change"
                    );
                    return Err(error);
                }
            }
        }
    }
    context
        .issue_lifecycle_workflow_starters
        .start_spiking(&notification)
        .await
}
