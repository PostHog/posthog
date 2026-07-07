use crate::core::{error::UnhandledError, types::notification::IngestionNotification};
use crate::modes::notifications::context::NotificationsContext;
use crate::modes::notifications::issue_handler::{
    handle_issue_created, handle_issue_reopened, handle_issue_spiking,
};

pub async fn handle_notification(
    context: &NotificationsContext,
    notification: IngestionNotification,
) -> Result<(), UnhandledError> {
    match notification {
        IngestionNotification::IssueCreated(issue_created) => {
            handle_issue_created(context, issue_created).await
        }
        IngestionNotification::IssueReopened(issue_reopened) => {
            handle_issue_reopened(context, issue_reopened).await
        }
        IngestionNotification::IssueSpiking(issue_spiking) => {
            handle_issue_spiking(context, issue_spiking).await
        }
    }
}
