use chrono::{DateTime, Utc};
use tracing::warn;
use uuid::Uuid;

use crate::core::{
    error::UnhandledError,
    types::notification::{IngestionNotification, IssueCreated, IssueReopened, IssueSpiking},
};
use crate::modes::notifications::analytics::{capture_issue_created, capture_issue_reopened};
use crate::modes::notifications::context::NotificationsContext;
use crate::modes::notifications::side_effects::{
    send_issue_created_alert_to_producer, send_issue_reopened_alert_to_producer,
    send_issue_spiking_alert_to_producer, send_new_fingerprint_event_to_producer,
};
use crate::modes::notifications::types::IssueNotificationData;

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

async fn handle_issue_created(
    context: &NotificationsContext,
    issue_created: IssueCreated,
) -> Result<(), UnhandledError> {
    let issue = load_issue(context, issue_created.team_id, issue_created.issue_id).await?;

    context
        .signal_client
        .emit_issue_created(&issue, &issue_created.event_properties);
    send_new_fingerprint_event_to_producer(
        &context.immediate_producer,
        &context.embedding_worker_topic,
        &issue,
        &issue_created.event_properties,
    )
    .await?;
    let sentry_integration = issue_created
        .event_properties
        .other
        .contains_key("$sentry_event_id");

    send_issue_created_alert_to_producer(
        &context.cyclotron_producer,
        &context.internal_events_topic,
        &issue,
        issue_created.assignee,
        issue_created.event_properties,
        &parse_notification_timestamp(&issue_created.event_timestamp, issue_created.event_uuid),
    )
    .await?;

    capture_issue_created(
        issue_created.team_id,
        issue_created.issue_id,
        sentry_integration,
    );

    Ok(())
}

async fn handle_issue_reopened(
    context: &NotificationsContext,
    issue_reopened: IssueReopened,
) -> Result<(), UnhandledError> {
    let issue = load_issue(context, issue_reopened.team_id, issue_reopened.issue_id).await?;

    context
        .signal_client
        .emit_issue_reopened(&issue, &issue_reopened.event_properties);
    capture_issue_reopened(issue_reopened.team_id, issue_reopened.issue_id);
    send_issue_reopened_alert_to_producer(
        &context.cyclotron_producer,
        &context.internal_events_topic,
        &issue,
        issue_reopened.assignee,
        issue_reopened.event_properties,
        &parse_notification_timestamp(&issue_reopened.event_timestamp, Uuid::nil()),
    )
    .await
}

async fn handle_issue_spiking(
    context: &NotificationsContext,
    issue_spiking: IssueSpiking,
) -> Result<(), UnhandledError> {
    let issue = load_issue(context, issue_spiking.team_id, issue_spiking.issue_id).await?;

    persist_spike_event(context, &issue_spiking).await?;
    context.signal_client.emit_issue_spiking(
        &issue,
        &issue_spiking.event_properties,
        issue_spiking.computed_baseline,
        issue_spiking.current_bucket_value,
    );

    send_issue_spiking_alert_to_producer(
        &context.cyclotron_producer,
        &context.internal_events_topic,
        &issue,
        issue_spiking.computed_baseline,
        issue_spiking.current_bucket_value,
    )
    .await?;

    Ok(())
}

async fn load_issue(
    context: &NotificationsContext,
    team_id: i32,
    issue_id: Uuid,
) -> Result<IssueNotificationData, UnhandledError> {
    sqlx::query_as::<_, IssueNotificationData>(
        r#"
        SELECT id, team_id, status, name, description, created_at
        FROM posthog_errortrackingissue
        WHERE id = $1 AND team_id = $2
        "#,
    )
    .bind(issue_id)
    .bind(team_id)
    .fetch_optional(&context.posthog_pool)
    .await?
    .ok_or_else(|| UnhandledError::Other(format!("issue {issue_id} for team {team_id} not found")))
}

async fn persist_spike_event(
    context: &NotificationsContext,
    issue_spiking: &IssueSpiking,
) -> Result<(), UnhandledError> {
    let id = Uuid::now_v7();
    let now = Utc::now();
    sqlx::query(
        r#"INSERT INTO posthog_errortrackingspikeevent
           (id, team_id, issue_id, detected_at, computed_baseline, current_bucket_value)
           VALUES ($1, $2, $3, $4, $5, $6)"#,
    )
    .bind(id)
    .bind(issue_spiking.team_id)
    .bind(issue_spiking.issue_id)
    .bind(now)
    .bind(issue_spiking.computed_baseline)
    .bind(issue_spiking.current_bucket_value as i32)
    .execute(&context.posthog_pool)
    .await?;

    Ok(())
}

fn parse_notification_timestamp(event_timestamp: &str, event_uuid: Uuid) -> DateTime<Utc> {
    common_types::format::parse_datetime_assuming_utc(event_timestamp).unwrap_or_else(|e| {
        warn!(
            event = event_uuid.to_string(),
            "Failed to get event timestamp, using current time, error: {:?}", e
        );
        Utc::now()
    })
}
