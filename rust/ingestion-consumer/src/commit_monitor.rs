//! Confirms that async commits land. librdkafka never reports the result of
//! a manual async commit (see the note on
//! [`crate::order_sentinel::SentinelContext`]), so a task fetches the group's
//! broker-committed offsets on an interval and reports them to the commit
//! sentinel.

use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{Consumer, StreamConsumer};
use tokio::task::JoinHandle;
use tracing::warn;

use crate::commit_sentinel::CommitSentinel;
use crate::order_sentinel::SentinelContext;

/// How often the monitor fetches the group's broker-committed offsets.
const COMMIT_MONITOR_INTERVAL: Duration = Duration::from_secs(30);

/// Aborts the wrapped task when dropped, covering every `process()` exit path.
pub struct AbortOnDrop(JoinHandle<()>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

/// Run the monitor until shutdown. Aborted when the guard drops, so a
/// consumer torn down mid-test doesn't keep the rdkafka client alive.
pub fn spawn_commit_monitor(
    consumer: Arc<StreamConsumer<SentinelContext>>,
    sentinel: Arc<CommitSentinel>,
    handle: Handle,
) -> AbortOnDrop {
    AbortOnDrop(tokio::spawn(run_commit_monitor(consumer, sentinel, handle)))
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
