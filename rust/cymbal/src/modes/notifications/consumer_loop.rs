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
