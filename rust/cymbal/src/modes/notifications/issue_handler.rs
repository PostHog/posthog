use chrono::{DateTime, Utc};
use tracing::warn;
use uuid::Uuid;

use crate::core::{
    error::UnhandledError,
    types::notification::{
        IssueCreated, IssueNotificationContext, IssueReopened, IssueSnapshot, IssueSpiking,
    },
};
use crate::modes::notifications::analytics::{capture_issue_created, capture_issue_reopened};
use crate::modes::notifications::context::NotificationsContext;
use crate::modes::notifications::side_effects::{
    send_issue_created_internal_event, send_issue_reopened_internal_event,
    send_issue_spiking_internal_event, send_new_fingerprint_event,
};
use crate::modes::notifications::types::IssueNotificationData;

pub async fn handle_issue_created(
    context: &NotificationsContext,
    notification: IssueCreated,
) -> Result<(), UnhandledError> {
    let IssueCreated {
        meta,
        issue,
        event_uuid,
        event_timestamp,
        assignee,
        ..
    } = notification;
    let IssueNotificationContext {
        issue_id,
        issue: issue_snapshot,
        event_properties,
    } = issue;
    let issue = issue_from_notification(meta.team_id, issue_id, issue_snapshot);

    send_new_fingerprint_event(
        &context.immediate_producer,
        &context.embedding_worker_topic,
        &issue,
        &event_properties,
    )
    .await?;
    let sentry_integration = event_properties.other.contains_key("$sentry_event_id");

    send_issue_created_internal_event(
        &context.cyclotron_producer,
        &context.internal_events_topic,
        meta.notification_id,
        &issue,
        assignee,
        &event_properties,
        &parse_notification_timestamp(&event_timestamp, event_uuid),
    )
    .await?;

    context
        .signal_client
        .emit_issue_created(&issue, &event_properties);

    capture_issue_created(meta.team_id, issue_id, sentry_integration);

    Ok(())
}

pub async fn handle_issue_reopened(
    context: &NotificationsContext,
    notification: IssueReopened,
) -> Result<(), UnhandledError> {
    let IssueReopened {
        meta,
        issue,
        event_timestamp,
        assignee,
    } = notification;
    let IssueNotificationContext {
        issue_id,
        issue: issue_snapshot,
        event_properties,
    } = issue;
    let issue = issue_from_notification(meta.team_id, issue_id, issue_snapshot);

    send_issue_reopened_internal_event(
        &context.cyclotron_producer,
        &context.internal_events_topic,
        meta.notification_id,
        &issue,
        assignee,
        &event_properties,
        &parse_notification_timestamp(&event_timestamp, Uuid::nil()),
    )
    .await?;

    context
        .signal_client
        .emit_issue_reopened(&issue, &event_properties);
    capture_issue_reopened(meta.team_id, issue_id);

    Ok(())
}

pub async fn handle_issue_spiking(
    context: &NotificationsContext,
    notification: IssueSpiking,
) -> Result<(), UnhandledError> {
    let IssueSpiking {
        meta,
        issue,
        computed_baseline,
        current_bucket_value,
    } = notification;
    let IssueNotificationContext {
        issue_id,
        issue: issue_snapshot,
        event_properties,
    } = issue;

    let issue_exists = persist_spike_event(
        context,
        meta.notification_id,
        meta.team_id,
        issue_id,
        computed_baseline,
        current_bucket_value,
    )
    .await?;
    if !issue_exists {
        warn!(
            notification_id = %meta.notification_id,
            team_id = meta.team_id,
            issue_id = %issue_id,
            "dropping spike notification for missing issue"
        );
        return Ok(());
    }

    let issue = issue_from_notification(meta.team_id, issue_id, issue_snapshot);

    send_issue_spiking_internal_event(
        &context.cyclotron_producer,
        &context.internal_events_topic,
        meta.notification_id,
        &issue,
        computed_baseline,
        current_bucket_value,
    )
    .await?;

    context.signal_client.emit_issue_spiking(
        &issue,
        &event_properties,
        computed_baseline,
        current_bucket_value,
    );

    Ok(())
}

fn issue_from_notification(
    team_id: i32,
    issue_id: Uuid,
    issue: IssueSnapshot,
) -> IssueNotificationData {
    IssueNotificationData {
        id: issue_id,
        team_id,
        status: issue.status,
        name: issue.name,
        description: issue.description,
        created_at: issue.created_at,
    }
}

async fn persist_spike_event(
    context: &NotificationsContext,
    notification_id: Uuid,
    team_id: i32,
    issue_id: Uuid,
    computed_baseline: f64,
    current_bucket_value: f64,
) -> Result<bool, UnhandledError> {
    let now = Utc::now();
    let result = sqlx::query(
        r#"WITH existing_issue AS (
               SELECT 1 FROM posthog_errortrackingissue
               WHERE team_id = $2 AND id = $3
               FOR KEY SHARE
           )
           INSERT INTO posthog_errortrackingspikeevent
           (id, team_id, issue_id, detected_at, computed_baseline, current_bucket_value)
           SELECT $1, $2, $3, $4, $5, $6 FROM existing_issue
           ON CONFLICT (id) DO NOTHING"#,
    )
    .bind(notification_id)
    .bind(team_id)
    .bind(issue_id)
    .bind(now)
    .bind(computed_baseline)
    .bind(current_bucket_value as i32)
    .execute(&context.posthog_pool)
    .await?;

    if result.rows_affected() > 0 {
        return Ok(true);
    }

    let issue_exists: bool = sqlx::query_scalar(
        r#"SELECT EXISTS(
            SELECT 1 FROM posthog_errortrackingissue WHERE team_id = $1 AND id = $2
        )"#,
    )
    .bind(team_id)
    .bind(issue_id)
    .fetch_one(&context.posthog_pool)
    .await?;

    Ok(issue_exists)
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
