use crate::core::{
    error::UnhandledError,
    types::notification::{IssueCreated, IssueReopened, IssueSpiking},
};
use crate::modes::notifications::analytics::{
    capture_issue_created, capture_issue_reopened, IssueCreatedDimensions,
};
use crate::modes::notifications::context::NotificationsContext;
use crate::modes::processing::types::ProcessedExceptionProperties;

pub async fn handle_issue_created(
    context: &NotificationsContext,
    notification: IssueCreated,
) -> Result<(), UnhandledError> {
    context
        .issue_lifecycle_workflow_starters
        .start_created(&notification)
        .await?;

    capture_issue_created(
        notification.meta.team_id,
        notification.issue.issue_id,
        issue_created_dimensions(&notification.issue.event_properties),
    );
    Ok(())
}

fn issue_created_dimensions(
    event_properties: &ProcessedExceptionProperties,
) -> IssueCreatedDimensions {
    IssueCreatedDimensions {
        sentry_integration: event_properties
            .properties()
            .contains_key("$sentry_event_id"),
        // The primary (first) exception of the chain — the one the issue is named after.
        exception_type: event_properties.types().first().cloned(),
        lib: event_properties
            .properties()
            .get("$lib")
            .and_then(|lib| lib.as_str())
            .map(str::to_string),
        fingerprint_version: event_properties
            .fingerprint_version()
            .map(|version| version.as_str()),
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn properties(json: serde_json::Value) -> ProcessedExceptionProperties {
        serde_json::from_value(json).unwrap()
    }

    #[test]
    fn reads_the_primary_exception_dimensions_off_the_event() {
        let dimensions = issue_created_dimensions(&properties(serde_json::json!({
            "$exception_list": [
                {"type": "TypeError", "value": "boom"},
                {"type": "Error", "value": "cause"},
            ],
            "$exception_fingerprint": "abc",
            "$exception_fingerprint_version": "v2",
            "$exception_fingerprint_record": [],
            "$exception_issue_id": uuid::Uuid::nil(),
            "$exception_handled": false,
            "$exception_types": ["TypeError", "Error"],
            "$exception_values": ["boom", "cause"],
            "$exception_sources": [],
            "$exception_functions": [],
            "$lib": "posthog-python",
            "$sentry_event_id": "deadbeef",
        })));

        assert_eq!(dimensions.exception_type.as_deref(), Some("TypeError"));
        assert_eq!(dimensions.lib.as_deref(), Some("posthog-python"));
        assert_eq!(dimensions.fingerprint_version, Some("v2"));
        assert!(dimensions.sentry_integration);
    }

    #[test]
    fn leaves_dimensions_unset_when_the_event_carries_none() {
        let dimensions = issue_created_dimensions(&properties(serde_json::json!({
            "$exception_list": [{"type": "Error", "value": "boom"}],
            "$exception_fingerprint": "abc",
            "$exception_fingerprint_record": [],
            "$exception_issue_id": uuid::Uuid::nil(),
            "$exception_handled": false,
            "$exception_types": [],
            "$exception_values": [],
            "$exception_sources": [],
            "$exception_functions": [],
        })));

        assert_eq!(dimensions.exception_type, None);
        assert_eq!(dimensions.lib, None);
        assert_eq!(dimensions.fingerprint_version, None);
        assert!(!dimensions.sentry_integration);
    }
}
