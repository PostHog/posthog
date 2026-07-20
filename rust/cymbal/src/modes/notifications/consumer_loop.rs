use std::time::Duration;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use tokio::sync::watch;
use tracing::{debug, error, info, warn};

use crate::core::types::notification::IngestionNotification;
use crate::modes::notifications::context::NotificationsContext;
use crate::modes::notifications::handler::handle_notification;

const NOTIFICATIONS_RECEIVED_TOTAL: &str = "cymbal_notifications_received_total";
const NOTIFICATIONS_HANDLED_TOTAL: &str = "cymbal_notifications_handled_total";
const NOTIFICATIONS_SKIPPED_TOTAL: &str = "cymbal_notifications_skipped_total";
const NOTIFICATIONS_KAFKA_ERRORS_TOTAL: &str = "cymbal_notifications_kafka_errors_total";
const NOTIFICATIONS_HANDLE_ERRORS_TOTAL: &str = "cymbal_notifications_handle_errors_total";
const NOTIFICATIONS_COMMIT_BATCH_SIZE: usize = 100;
const NOTIFICATIONS_FETCH_BATCH_TIMEOUT: Duration = Duration::from_millis(250);

/// Receive messages until shutdown. Offsets are stored only after successful
/// handling, then explicitly committed after each fetched batch. Serde and empty
/// failures are auto-stored as poison pills inside `json_recv_batch`, so this
/// loop also explicitly commits those stored offsets.
pub async fn consume_loop(
    consumer: SingleTopicConsumer,
    context: NotificationsContext,
    mut shutdown_rx: watch::Receiver<bool>,
) {
    let mut pending_offsets = 0usize;

    loop {
        tokio::select! {
            biased;
            changed = shutdown_rx.changed() => {
                if changed.is_err() || *shutdown_rx.borrow() {
                    info!("notifications consumer shutting down");
                    commit_pending_offsets(&consumer, &mut pending_offsets, "shutdown");
                    break;
                }
            }
            batch = consumer.json_recv_batch::<IngestionNotification>(
                NOTIFICATIONS_COMMIT_BATCH_SIZE,
                NOTIFICATIONS_FETCH_BATCH_TIMEOUT,
            ) => {
                handle_notification_batch(&consumer, &context, batch, &mut pending_offsets).await;
                commit_pending_offsets(&consumer, &mut pending_offsets, "batch");
            }
        }
    }
}

async fn handle_notification_batch(
    consumer: &SingleTopicConsumer,
    context: &NotificationsContext,
    batch: Vec<Result<(IngestionNotification, Offset), RecvErr>>,
    pending_offsets: &mut usize,
) {
    for result in batch {
        match result {
            Ok((notification, offset)) => {
                let offset = match validate_notification_with_offset(
                    &notification,
                    offset,
                    Offset::store,
                    pending_offsets,
                ) {
                    Ok(Some(offset)) => offset,
                    Ok(None) => continue,
                    Err(e) => panic!("failed to store invalid notification offset: {e}"),
                };

                log_notification_summary(&notification);
                metrics::counter!(NOTIFICATIONS_RECEIVED_TOTAL).increment(1);
                match handle_notification(context, notification).await {
                    Ok(()) => {
                        metrics::counter!(NOTIFICATIONS_HANDLED_TOTAL).increment(1);
                        // `commit_consumer_state` only commits offsets explicitly stored on the consumer.
                        if let Err(e) = offset.store() {
                            panic!("failed to store notification offset: {e}");
                        }
                        *pending_offsets += 1;
                    }
                    Err(e) => {
                        metrics::counter!(NOTIFICATIONS_HANDLE_ERRORS_TOTAL).increment(1);
                        commit_pending_offsets(consumer, pending_offsets, "before_panic");
                        panic!("failed to handle notification: {e}");
                    }
                }
            }
            Err(RecvErr::Serde(e)) => {
                warn!(error = %e, "notification serde error (poison pill skipped)");
                metrics::counter!(NOTIFICATIONS_SKIPPED_TOTAL, "reason" => "serde").increment(1);
                *pending_offsets += 1;
            }
            Err(RecvErr::Empty) => {
                metrics::counter!(NOTIFICATIONS_SKIPPED_TOTAL, "reason" => "empty").increment(1);
                *pending_offsets += 1;
            }
            Err(RecvErr::Kafka(e)) => {
                error!(error = %e, "notifications kafka error");
                metrics::counter!(NOTIFICATIONS_KAFKA_ERRORS_TOTAL).increment(1);
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
    }
}

fn validate_notification_with_offset<O, E>(
    notification: &IngestionNotification,
    offset: O,
    store_offset: impl FnOnce(O) -> Result<(), E>,
    pending_offsets: &mut usize,
) -> Result<Option<O>, E> {
    if let Err(e) = notification.validate() {
        warn!(error = %e, "notification validation error (poison pill skipped)");
        metrics::counter!(NOTIFICATIONS_SKIPPED_TOTAL, "reason" => "validation").increment(1);
        store_offset(offset)?;
        *pending_offsets += 1;
        return Ok(None);
    }

    Ok(Some(offset))
}

fn commit_pending_offsets(
    consumer: &SingleTopicConsumer,
    pending_offsets: &mut usize,
    reason: &str,
) {
    if *pending_offsets == 0 {
        return;
    }

    if let Err(e) = consumer.commit() {
        panic!("failed to commit notification offsets: {e}");
    }

    debug!(
        count = *pending_offsets,
        reason, "committed notification offsets"
    );
    *pending_offsets = 0;
}

fn log_notification_summary(notification: &IngestionNotification) {
    match notification {
        IngestionNotification::IssueCreated(issue_created) => {
            debug!(
                notification_type = "issue_created",
                notification_id = %issue_created.meta.notification_id,
                team_id = issue_created.meta.team_id,
                issue_id = %issue_created.issue.issue_id,
                event_uuid = %issue_created.event_uuid,
                "received error-tracking ingestion notification"
            );
        }
        IngestionNotification::IssueReopened(issue_reopened) => {
            debug!(
                notification_type = "issue_reopened",
                notification_id = %issue_reopened.meta.notification_id,
                team_id = issue_reopened.meta.team_id,
                issue_id = %issue_reopened.issue.issue_id,
                "received error-tracking ingestion notification"
            );
        }
        IngestionNotification::IssueSpiking(issue_spiking) => {
            debug!(
                notification_type = "issue_spiking",
                notification_id = %issue_spiking.meta.notification_id,
                team_id = issue_spiking.meta.team_id,
                issue_id = %issue_spiking.issue.issue_id,
                "received error-tracking ingestion notification"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    fn issue_created(issue_id: Uuid, property_issue_id: Uuid) -> IngestionNotification {
        serde_json::from_value(serde_json::json!({
            "type": "issue_created",
            "notification_id": Uuid::nil(),
            "team_id": 42,
            "issue_id": issue_id,
            "issue": {
                "name": "Example",
                "description": "Example issue",
                "status": "active",
                "created_at": "1970-01-01T00:00:00Z"
            },
            "event_properties": {
                "$exception_list": [{"type": "Error", "value": "boom"}],
                "$exception_fingerprint": "abc",
                "$exception_fingerprint_record": [{"type": "manual"}],
                "$exception_issue_id": property_issue_id,
                "$exception_handled": false,
                "$exception_types": ["Error"],
                "$exception_values": ["boom"],
                "$exception_sources": [],
                "$exception_functions": []
            },
            "fingerprint": "abc",
            "event_uuid": Uuid::nil(),
            "event_timestamp": "1970-01-01T00:00:00Z",
            "assignee": null
        }))
        .unwrap()
    }

    #[test]
    fn invalid_notification_is_stored_and_does_not_block_the_next_valid_item() {
        let issue_id = Uuid::now_v7();
        let invalid = issue_created(issue_id, Uuid::now_v7());
        let valid = issue_created(issue_id, issue_id);
        let mut pending_offsets = 0;
        let mut stored = Vec::new();
        let mut handled = Vec::new();

        let result = validate_notification_with_offset(
            &invalid,
            10,
            |offset| {
                stored.push(offset);
                Ok::<_, ()>(())
            },
            &mut pending_offsets,
        )
        .unwrap();
        if let Some(offset) = result {
            handled.push(offset);
        }

        let result = validate_notification_with_offset(
            &valid,
            11,
            |offset| {
                stored.push(offset);
                Ok::<_, ()>(())
            },
            &mut pending_offsets,
        )
        .unwrap();
        if let Some(offset) = result {
            handled.push(offset);
        }

        assert_eq!(stored, vec![10]);
        assert_eq!(handled, vec![11]);
        assert_eq!(pending_offsets, 1);
    }
}
