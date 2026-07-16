use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use futures::stream::{self, StreamExt};
use tokio::sync::watch;
use tracing::{debug, error, info, warn};

use crate::core::error::UnhandledError;
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

/// Receive messages until shutdown. Each fetched batch is split into per-issue
/// groups (the producer partitions by `team_id:issue_id`), which are handled
/// concurrently up to `max_concurrency`; messages within a group stay
/// sequential, so per-issue ordering is preserved. Offsets are stored per
/// partition only up to the first failure and committed after each batch, so a
/// crash never skips an unhandled message. Serde and empty failures are
/// auto-stored as poison pills inside `json_recv_batch`; clean batches commit
/// those stored offsets too, but a failed batch commits only the explicit
/// success prefix — a pill's fetch-time store can sit past the failed message
/// and must not be committed ahead of it.
pub async fn consume_loop(
    consumer: SingleTopicConsumer,
    context: NotificationsContext,
    max_concurrency: usize,
    mut shutdown_rx: watch::Receiver<bool>,
) {
    let max_concurrency = max_concurrency.max(1);

    loop {
        tokio::select! {
            biased;
            changed = shutdown_rx.changed() => {
                if changed.is_err() || *shutdown_rx.borrow() {
                    info!("notifications consumer shutting down");
                    break;
                }
            }
            batch = consumer.json_recv_batch::<IngestionNotification>(
                NOTIFICATIONS_COMMIT_BATCH_SIZE,
                NOTIFICATIONS_FETCH_BATCH_TIMEOUT,
            ) => {
                handle_notification_batch(&consumer, &context, batch, max_concurrency).await;
            }
        }
    }
}

struct MessageOutcome {
    batch_index: usize,
    offset: Offset,
    result: HandleResult,
}

enum HandleResult {
    Handled,
    Failed(UnhandledError),
    /// Not attempted because an earlier failure was already observed. Emitting
    /// an outcome keeps the message visible to `storable_offsets`, so a later
    /// success on its partition can't be committed past it; it redelivers
    /// after the panic.
    Skipped,
}

async fn handle_notification_batch(
    consumer: &SingleTopicConsumer,
    context: &NotificationsContext,
    batch: Vec<Result<(IngestionNotification, Offset), RecvErr>>,
    max_concurrency: usize,
) {
    // Poison pills already had their offsets stored inside `json_recv_batch`;
    // count them so clean batches commit them even when nothing else succeeds.
    let mut stored = 0usize;
    let mut messages = Vec::new();

    for (batch_index, result) in batch.into_iter().enumerate() {
        match result {
            Ok((notification, offset)) => {
                log_notification_summary(&notification);
                metrics::counter!(NOTIFICATIONS_RECEIVED_TOTAL).increment(1);
                messages.push((batch_index, notification, offset));
            }
            Err(RecvErr::Serde(e)) => {
                warn!(error = %e, "notification serde error (poison pill skipped)");
                metrics::counter!(NOTIFICATIONS_SKIPPED_TOTAL, "reason" => "serde").increment(1);
                stored += 1;
            }
            Err(RecvErr::Empty) => {
                metrics::counter!(NOTIFICATIONS_SKIPPED_TOTAL, "reason" => "empty").increment(1);
                stored += 1;
            }
            Err(RecvErr::Kafka(e)) => {
                error!(error = %e, "notifications kafka error");
                metrics::counter!(NOTIFICATIONS_KAFKA_ERRORS_TOTAL).increment(1);
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
    }

    let groups = group_preserving_order(messages, |(_, notification, _)| {
        notification.partition_key()
    });

    // The whole batch panics (and redelivers) on any failure, so once one is
    // observed, handling more messages only creates side effects that will be
    // emitted again on redelivery. Stop starting new work: everything not yet
    // in flight is skipped, bounding duplicates to the groups already running.
    // This also halts the failed group itself, preserving per-issue ordering.
    let failed = AtomicBool::new(false);
    let mut outcomes: Vec<MessageOutcome> = stream::iter(groups.into_iter().map(|group| async {
        let mut outcomes = Vec::with_capacity(group.len());
        for (batch_index, notification, offset) in group {
            if failed.load(Ordering::Relaxed) {
                outcomes.push(MessageOutcome {
                    batch_index,
                    offset,
                    result: HandleResult::Skipped,
                });
                continue;
            }
            match handle_notification(context, notification).await {
                Ok(()) => {
                    metrics::counter!(NOTIFICATIONS_HANDLED_TOTAL).increment(1);
                    outcomes.push(MessageOutcome {
                        batch_index,
                        offset,
                        result: HandleResult::Handled,
                    });
                }
                Err(e) => {
                    metrics::counter!(NOTIFICATIONS_HANDLE_ERRORS_TOTAL).increment(1);
                    failed.store(true, Ordering::Relaxed);
                    outcomes.push(MessageOutcome {
                        batch_index,
                        offset,
                        result: HandleResult::Failed(e),
                    });
                }
            }
        }
        outcomes
    }))
    .buffer_unordered(max_concurrency)
    .concat()
    .await;

    outcomes.sort_by_key(|outcome| outcome.batch_index);

    let storable: Vec<bool> = storable_offsets(outcomes.iter().map(|outcome| {
        (
            outcome.offset.partition(),
            matches!(outcome.result, HandleResult::Handled),
        )
    }));

    let mut first_error = None;
    // Per-partition next-offsets of the stored successes; offsets ascend per
    // partition, so the last insert holds the max.
    let mut committable: HashMap<i32, i64> = HashMap::new();
    for (outcome, store) in outcomes.into_iter().zip(storable) {
        match outcome.result {
            HandleResult::Failed(error) => {
                first_error.get_or_insert(error);
                continue;
            }
            HandleResult::Skipped => continue,
            HandleResult::Handled => {}
        }
        if !store {
            continue;
        }
        let (partition, next_offset) = (outcome.offset.partition(), outcome.offset.get_value() + 1);
        // `commit_consumer_state` only commits offsets explicitly stored on the consumer.
        if let Err(e) = outcome.offset.store() {
            panic!("failed to store notification offset: {e}");
        }
        committable.insert(partition, next_offset);
        stored += 1;
    }

    let Some(error) = first_error else {
        // `stored` may be poison pills alone; guard the commit — committing with
        // nothing stored fails with NO_OFFSET.
        if stored > 0 {
            if let Err(e) = consumer.commit() {
                panic!("failed to commit notification offsets: {e}");
            }
            debug!(count = stored, "committed notification offsets");
        }
        return;
    };

    // A state-wide commit here would also publish poison-pill offsets auto-stored
    // at fetch time inside `json_recv_batch`, which can sit past the failed
    // message on the same partition and permanently skip it. Commit only the
    // explicit success prefix; pill stores die with the panic and the pills are
    // redelivered, re-skipped, and committed by a later clean batch.
    let offsets: Vec<(i32, i64)> = committable.into_iter().collect();
    if !offsets.is_empty() {
        if let Err(e) = consumer.commit_partition_offsets(&offsets) {
            panic!("failed to commit notification offsets: {e}");
        }
        debug!(
            count = offsets.len(),
            "committed notification success-prefix offsets before panic"
        );
    }

    panic!("failed to handle notification: {error}");
}

/// Group items by key, preserving each group's original item order. Group
/// order follows first appearance, keeping batches deterministic.
fn group_preserving_order<T, K: Fn(&T) -> String>(items: Vec<T>, key_fn: K) -> Vec<Vec<T>> {
    let mut key_indexes: HashMap<String, usize> = HashMap::new();
    let mut groups: Vec<Vec<T>> = Vec::new();

    for item in items {
        let key = key_fn(&item);
        let index = *key_indexes.entry(key).or_insert_with(|| {
            groups.push(Vec::new());
            groups.len() - 1
        });
        groups[index].push(item);
    }

    groups
}

/// Given `(partition, succeeded)` per message in batch (= per-partition offset)
/// order, mark which offsets are safe to store: within a partition, only
/// messages before the first failure. Storing a later offset would mark the
/// failed message as processed and Kafka would never redeliver it.
fn storable_offsets(outcomes: impl Iterator<Item = (i32, bool)>) -> Vec<bool> {
    let mut blocked: HashSet<i32> = HashSet::new();

    outcomes
        .map(|(partition, succeeded)| {
            if !succeeded {
                blocked.insert(partition);
                return false;
            }
            !blocked.contains(&partition)
        })
        .collect()
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

    #[test]
    fn storable_offsets_blocks_partition_after_failure_only() {
        // Partitions interleaved in offset order: a failure on partition 0 must
        // block later partition-0 offsets (or redelivery would skip the failed
        // message) while partition 1 keeps storing.
        let outcomes = vec![
            (0, true),
            (1, true),
            (0, false),
            (1, true),
            (0, true),
            (0, true),
            (1, false),
            (1, true),
        ];

        let storable = storable_offsets(outcomes.into_iter());

        assert_eq!(
            storable,
            vec![true, true, false, true, false, false, false, false]
        );
    }

    #[test]
    fn group_preserving_order_keeps_per_key_order() {
        let items = vec![("a", 1), ("b", 2), ("a", 3), ("c", 4), ("b", 5)];

        let groups = group_preserving_order(items, |(key, _)| key.to_string());

        assert_eq!(
            groups,
            vec![
                vec![("a", 1), ("a", 3)],
                vec![("b", 2), ("b", 5)],
                vec![("c", 4)],
            ]
        );
    }
}
