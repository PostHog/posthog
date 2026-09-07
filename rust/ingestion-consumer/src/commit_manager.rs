//! Offset commits for the ingestion consumer: the sentinel check on every
//! span, the rdkafka commit, and the monitor that confirms async commits
//! landed on the broker.

use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::TopicPartition;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::TopicPartitionList;
use tokio::task::JoinHandle;
use tracing::warn;

use crate::order_sentinel::{CommitSentinel, OffsetSpan, SentinelContext};

/// How often the commit monitor fetches the group's broker-committed offsets.
const COMMIT_MONITOR_INTERVAL: Duration = Duration::from_secs(30);

/// Submits offset commits for the consumer and verifies they land.
pub(crate) struct CommitManager {
    consumer: Arc<StreamConsumer<SentinelContext>>,
    /// Validates commit contiguity/monotonicity per partition. Shared with the
    /// consumer's [`SentinelContext`], which resets baselines on rebalance.
    sentinel: Arc<CommitSentinel>,
}

impl CommitManager {
    pub(crate) fn new(consumer: Arc<StreamConsumer<SentinelContext>>) -> Self {
        let sentinel = consumer.context().commit_sentinel();
        Self { consumer, sentinel }
    }

    /// Validate and submit one commit to Kafka.
    pub(crate) fn commit<'a>(
        &self,
        spans: impl IntoIterator<Item = (&'a TopicPartition, &'a OffsetSpan)>,
    ) -> anyhow::Result<()> {
        let spans: Vec<_> = spans.into_iter().collect();
        // Validate contiguity/monotonicity per partition before committing, so
        // a violation is attributed to the batch that caused it.
        self.sentinel.check_commit(spans.iter().copied());

        let mut tpl = TopicPartitionList::new();
        for (topic_partition, span) in &spans {
            // Commit offset + 1 (Kafka convention: committed offset = next to read)
            tpl.add_partition_offset(
                &topic_partition.topic,
                topic_partition.partition,
                rdkafka::Offset::Offset(span.last + 1),
            )?;
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        counter!("ingestion_consumer_offset_commits_total").increment(1);

        Ok(())
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
