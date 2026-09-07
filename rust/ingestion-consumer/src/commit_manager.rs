//! Offset commits for the ingestion consumer. Frontiers arrive one partition
//! at a time as work completes; the manager checks each against the commit
//! sentinel at once and commits the latest per partition on an interval, so
//! the commit rate is bounded by the interval rather than by how often
//! frontiers move.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use common_kafka_consumer::{Offset, TopicPartition};
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::TopicPartitionList;
use tokio::task::JoinHandle;
use tracing::warn;

use crate::order_sentinel::{CommitSentinel, OffsetSpan, SentinelContext};

/// How often the commit monitor fetches the group's broker-committed offsets.
const COMMIT_MONITOR_INTERVAL: Duration = Duration::from_secs(30);

/// The next-to-read offset each partition is ready to commit, awaiting the
/// next flush. Shared with the consumer's [`SentinelContext`], which drops a
/// partition's entry when the partition leaves the assignment: a commit
/// issued for a partition another member now owns could move the group's
/// offset back behind that member's progress.
#[derive(Default)]
pub struct PendingCommits {
    next_to_read: Mutex<HashMap<TopicPartition, Offset>>,
}

impl PendingCommits {
    pub fn new() -> Self {
        Self::default()
    }

    /// Replace the partition's pending offset. Frontiers only move forward,
    /// so the latest one covers every earlier one.
    fn record(&self, topic_partition: &TopicPartition, next_to_read: Offset) {
        self.next_to_read
            .lock()
            .unwrap()
            .insert(topic_partition.clone(), next_to_read);
    }

    /// Drop the pending offsets of partitions leaving the assignment.
    pub fn forget_partitions<'a>(
        &self,
        topic_partitions: impl IntoIterator<Item = (&'a str, i32)>,
    ) {
        let mut pending = self.next_to_read.lock().unwrap();
        for (topic, partition) in topic_partitions {
            pending.remove(&TopicPartition::new(topic, partition));
        }
    }

    /// Take everything pending, leaving nothing behind.
    fn take(&self) -> HashMap<TopicPartition, Offset> {
        std::mem::take(&mut *self.next_to_read.lock().unwrap())
    }
}

/// Submits offset commits for the consumer and verifies they land.
pub(crate) struct CommitManager {
    consumer: Arc<StreamConsumer<SentinelContext>>,
    /// Validates commit contiguity/monotonicity per partition. Shared with the
    /// consumer's [`SentinelContext`], which resets baselines on rebalance.
    sentinel: Arc<CommitSentinel>,
    pending: Arc<PendingCommits>,
    interval: Duration,
}

impl CommitManager {
    pub(crate) fn new(consumer: Arc<StreamConsumer<SentinelContext>>, interval: Duration) -> Self {
        let sentinel = consumer.context().commit_sentinel();
        let pending = consumer.context().pending_commits();
        Self {
            consumer,
            sentinel,
            pending,
            interval,
        }
    }

    /// A partition's frontier moved: `span` is the work now ready to commit,
    /// last-processed, in the representation the sentinel checks. The check
    /// runs here, so a violation is attributed to the work that caused it;
    /// the commit itself waits for the next flush.
    pub(crate) fn on_frontier(&self, topic_partition: &TopicPartition, span: OffsetSpan) {
        self.sentinel.check_commit([(topic_partition, &span)]);
        self.pending.record(topic_partition, Offset(span.last + 1));
    }

    /// Commit every pending frontier in one call. Nothing pending commits
    /// nothing.
    pub(crate) fn flush(&self) -> anyhow::Result<()> {
        let pending = self.pending.take();
        if pending.is_empty() {
            return Ok(());
        }
        let mut tpl = TopicPartitionList::new();
        for (topic_partition, next_to_read) in &pending {
            tpl.add_partition_offset(
                &topic_partition.topic,
                topic_partition.partition,
                rdkafka::Offset::Offset(next_to_read.0),
            )?;
        }
        self.consumer.commit(&tpl, CommitMode::Async)?;
        counter!("ingestion_consumer_offset_commits_total").increment(1);
        Ok(())
    }

    /// Flush on the interval until shutdown. A failed commit fails the
    /// process, as it would have when the consumer loop committed inline.
    /// Aborted when the guard drops.
    pub(crate) fn spawn_flusher(self: &Arc<Self>, handle: Handle) -> AbortOnDrop {
        let manager = Arc::clone(self);
        AbortOnDrop(tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = handle.shutdown_recv() => return,
                    _ = tokio::time::sleep(manager.interval) => {}
                }
                if let Err(err) = manager.flush() {
                    handle.signal_failure(format!("Offset commit failed: {err:#}"));
                    return;
                }
            }
        }))
    }

    /// Verify async commits actually land: librdkafka drops the result of
    /// manual async commits (see the note on [`SentinelContext`]), so a task
    /// polls the broker's committed offsets instead. Aborted when the guard
    /// drops, so a consumer torn down mid-test doesn't keep the rdkafka
    /// client alive.
    pub(crate) fn spawn_monitor(&self, handle: Handle) -> AbortOnDrop {
        AbortOnDrop(tokio::spawn(run_commit_monitor(
            Arc::clone(&self.consumer),
            Arc::clone(&self.sentinel),
            handle,
        )))
    }
}

/// Aborts the wrapped task when dropped, covering every `process()` exit path.
pub(crate) struct AbortOnDrop(JoinHandle<()>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

/// Periodically fetch the broker's committed offsets for the current
/// assignment (an OffsetFetch round trip) and feed them to the commit
/// sentinel, which compares them against attempted commits and stamps the
/// last-successful-commit gauge on progress.
async fn run_commit_monitor(
    consumer: Arc<StreamConsumer<SentinelContext>>,
    sentinel: Arc<CommitSentinel>,
    handle: Handle,
) {
    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => return,
            _ = tokio::time::sleep(COMMIT_MONITOR_INTERVAL) => {}
        }

        let fetch_consumer = Arc::clone(&consumer);
        // assignment() and committed_offsets() block on librdkafka.
        let fetched = tokio::task::spawn_blocking(move || {
            let assignment = fetch_consumer.assignment()?;
            if assignment.count() == 0 {
                return Ok(None);
            }
            fetch_consumer
                .committed_offsets(assignment, Duration::from_secs(5))
                .map(Some)
        })
        .await;

        match fetched {
            Ok(Ok(Some(committed))) => {
                let observed: Vec<(String, i32, i64)> = committed
                    .elements()
                    .iter()
                    .filter_map(|e| match e.offset() {
                        rdkafka::Offset::Offset(offset) => {
                            Some((e.topic().to_string(), e.partition(), offset))
                        }
                        // Invalid = no offset stored for the partition yet.
                        _ => None,
                    })
                    .collect();
                sentinel.observe_broker_committed(observed);
            }
            Ok(Ok(None)) => {} // no assignment yet (e.g. before first rebalance)
            Ok(Err(err)) => {
                counter!("ingestion_consumer_commit_monitor_errors_total").increment(1);
                warn!(error = %err, "Commit monitor failed to fetch committed offsets");
            }
            Err(err) => {
                counter!("ingestion_consumer_commit_monitor_errors_total").increment(1);
                warn!(error = %err, "Commit monitor task join error");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tp(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    #[test]
    fn the_latest_frontier_per_partition_is_what_flushes() {
        let pending = PendingCommits::new();
        pending.record(&tp(0), Offset(10));
        pending.record(&tp(1), Offset(20));
        pending.record(&tp(0), Offset(12));

        let taken = pending.take();
        assert_eq!(taken.len(), 2);
        assert_eq!(taken[&tp(0)], Offset(12));
        assert_eq!(taken[&tp(1)], Offset(20));
        assert!(pending.take().is_empty(), "a take leaves nothing behind");
    }

    #[test]
    fn a_forgotten_partition_has_nothing_to_flush() {
        let pending = PendingCommits::new();
        pending.record(&tp(0), Offset(10));
        pending.record(&tp(1), Offset(20));

        pending.forget_partitions([("events", 0)]);

        let taken = pending.take();
        assert_eq!(taken.len(), 1);
        assert_eq!(taken[&tp(1)], Offset(20));
    }
}
