//! The commit sentinel: an always-on observer that turns the consumer's
//! commit guarantee into alertable metrics.
//!
//! **Commit confirmation**: librdkafka never reports the result of a manual
//! async commit (see the note on [`crate::order_sentinel::SentinelContext`]),
//! so the commit monitor fetches the group's broker-committed offsets and
//! feeds [`CommitSentinel::observe_broker_committed`], which emits
//! `ingestion_consumer_broker_committed_offset` and
//! `ingestion_consumer_commit_confirmation_lag` gauges and stamps
//! `ingestion_consumer_last_successful_commit_timestamp_seconds` on progress.
//!
//! The sentinel wraps the [`CommitPacer`] the consumer hands its frontiers
//! to: every take passes through it on the way out. It is a pure observer:
//! it never changes what is committed.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use common_kafka_consumer::{Offset, TakenFrontier, TopicPartition};
use metrics::gauge;

use crate::commit_pacer::CommitPacer;

/// Per-partition commit tracking: what this process asked Kafka to commit
/// (attempted) and what the broker has confirmed as the group's committed
/// offset (observed by the commit monitor via OffsetFetch).
#[derive(Default, Clone, Copy)]
struct PartitionCommits {
    /// The offset value last handed out for commit (Kafka "next to read").
    attempted: Option<i64>,
    /// The broker-confirmed committed offset from the last monitor poll.
    confirmed: Option<i64>,
}

pub struct CommitSentinel {
    partitions: Mutex<HashMap<(String, i32), PartitionCommits>>,
    /// Kill switch (`CONSUMER_ORDER_SENTINEL_ENABLED`). When off, checks
    /// no-op and no state accumulates.
    enabled: AtomicBool,
    /// The pacer being observed.
    inner: CommitPacer,
}

impl CommitSentinel {
    pub fn new(inner: CommitPacer) -> Self {
        Self {
            partitions: Mutex::new(HashMap::new()),
            enabled: AtomicBool::new(true),
            inner,
        }
    }

    pub fn set_enabled(&self, enabled: bool) {
        self.enabled.store(enabled, Ordering::Relaxed);
    }

    pub fn advance_frontier(&self, topic_partition: &TopicPartition, taken: TakenFrontier) {
        self.inner.advance_frontier(topic_partition, taken);
    }

    /// Partitions leaving the assignment: drop their baselines, and whatever
    /// the pacer holds for them.
    pub fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.forget_baselines(topic_partitions);
        self.inner.forget_partitions(topic_partitions);
    }

    pub fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        let offsets = self.inner.take_due(now)?;
        self.record_attempted(&offsets);
        Some(offsets)
    }

    pub fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>> {
        let offsets = self.inner.take_all()?;
        self.record_attempted(&offsets);
        Some(offsets)
    }

    fn record_attempted(&self, offsets: &HashMap<TopicPartition, Offset>) {
        if !self.enabled.load(Ordering::Relaxed) {
            return;
        }
        let mut partitions = self.partitions.lock().unwrap();
        for (topic_partition, offset) in offsets {
            let topic = &topic_partition.topic;
            let partition = topic_partition.partition;
            partitions
                .entry((topic.clone(), partition))
                .or_default()
                .attempted = Some(offset.0);
            gauge!(
                "ingestion_consumer_committed_offset",
                "topic" => topic.clone(),
                "partition" => partition.to_string(),
            )
            .set(offset.0 as f64);
        }
    }

    /// Feed broker-confirmed committed offsets (from an OffsetFetch of the
    /// group's assigned partitions) and compare against what this process
    /// attempted. Emits per-partition gauges:
    ///
    /// - `ingestion_consumer_broker_committed_offset` — the group's committed
    ///   offset as the broker reports it;
    /// - `ingestion_consumer_commit_confirmation_lag` — attempted minus
    ///   confirmed. Transiently positive while async commits are in flight;
    ///   persistently positive means commits are being submitted but not
    ///   landing (e.g. a stuck coordinator).
    ///
    /// Returns true when commits verifiably progressed since the last
    /// observation — the broker offset advanced, or everything attempted is
    /// confirmed — so the caller can stamp the last-successful-commit gauge.
    pub fn observe_broker_committed(
        &self,
        observed: impl IntoIterator<Item = (String, i32, i64)>,
    ) -> bool {
        if !self.enabled.load(Ordering::Relaxed) {
            return false;
        }
        let mut partitions = self.partitions.lock().unwrap();
        let mut advanced = false;

        for (topic, partition, committed) in observed {
            gauge!(
                "ingestion_consumer_broker_committed_offset",
                "topic" => topic.clone(),
                "partition" => partition.to_string(),
            )
            .set(committed as f64);

            let state = partitions.entry((topic.clone(), partition)).or_default();
            if let Some(attempted) = state.attempted {
                gauge!(
                    "ingestion_consumer_commit_confirmation_lag",
                    "topic" => topic.clone(),
                    "partition" => partition.to_string(),
                )
                .set((attempted - committed).max(0) as f64);
            }
            // Only an increase over a *previous* observation counts as
            // progress — the first poll baselines (the broker may be reporting
            // a prior incarnation's commits, which say nothing about ours).
            if state.confirmed.is_some_and(|prev| committed > prev) {
                advanced = true;
            }
            state.confirmed = Some(committed);
        }

        let all_confirmed = {
            let attempted_any = partitions.values().any(|s| s.attempted.is_some());
            attempted_any
                && partitions.values().all(|s| match s.attempted {
                    Some(attempted) => s.confirmed.is_some_and(|c| c >= attempted),
                    None => true,
                })
        };

        let progressed = advanced || all_confirmed;
        if progressed {
            gauge!("ingestion_consumer_last_successful_commit_timestamp_seconds").set(
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs_f64(),
            );
        }
        progressed
    }

    /// Drop the baselines for departing partitions: another group member may
    /// commit them in between, so their confirmation lag no longer means
    /// anything here.
    fn forget_baselines(&self, topic_partitions: &[TopicPartition]) {
        let mut partitions = self.partitions.lock().unwrap();
        for topic_partition in topic_partitions {
            let (topic, partition) = (&topic_partition.topic, topic_partition.partition);
            let forgotten = partitions.remove(&(topic.clone(), partition));
            if forgotten.is_some_and(|state| state.attempted.is_some()) {
                let topic: Arc<str> = Arc::from(topic.as_str());
                let partition: Arc<str> = Arc::from(partition.to_string());
                gauge!(
                    "ingestion_consumer_commit_confirmation_lag",
                    "topic" => topic,
                    "partition" => partition,
                )
                .set(0.0);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use crate::commit_pacer::test_support::{taken, tp};

    use super::*;

    fn sentinel() -> CommitSentinel {
        CommitSentinel::new(CommitPacer::immediate())
    }

    fn attempt(sentinel: &CommitSentinel, topic: &str, partition: i32, first: i64, offset: i64) {
        sentinel.advance_frontier(&TopicPartition::new(topic, partition), taken(first, offset));
        sentinel.take_due(Instant::now()).expect("due");
    }

    #[test]
    fn broker_observation_baselines_then_tracks_progress() {
        let sentinel = sentinel();
        attempt(&sentinel, "t", 0, 0, 100);
        // First poll baselines: a stale broker offset (previous incarnation)
        // is not evidence that OUR commits landed.
        assert!(!sentinel.observe_broker_committed([("t".to_string(), 0, 40)]));
        // Broker offset advancing across polls = commits are landing.
        assert!(sentinel.observe_broker_committed([("t".to_string(), 0, 80)]));
        // No advance and still behind the attempted offset = no progress.
        assert!(!sentinel.observe_broker_committed([("t".to_string(), 0, 80)]));
        // Catching up to everything attempted also counts as progress.
        assert!(sentinel.observe_broker_committed([("t".to_string(), 0, 100)]));
        // Fully confirmed and idle: repeated identical polls stay "progressed"
        // via the all-confirmed arm, keeping the liveness gauge fresh.
        assert!(sentinel.observe_broker_committed([("t".to_string(), 0, 100)]));
    }

    #[test]
    fn broker_observation_requires_every_attempted_partition_confirmed() {
        let sentinel = sentinel();
        attempt(&sentinel, "t", 0, 0, 100);
        attempt(&sentinel, "t", 1, 0, 10);
        sentinel.observe_broker_committed([("t".to_string(), 0, 100), ("t".to_string(), 1, 5)]);
        // Partition 0 fully confirmed but partition 1 stuck below attempted and
        // not advancing: not progress.
        assert!(!sentinel
            .observe_broker_committed([("t".to_string(), 0, 100), ("t".to_string(), 1, 5)]));
    }

    #[test]
    fn a_frontier_the_pacer_still_holds_is_not_an_attempted_commit() {
        let sentinel = CommitSentinel::new(CommitPacer::every(Duration::from_secs(3600)));
        attempt(&sentinel, "events", 0, 0, 10);
        sentinel.advance_frontier(&tp(0), taken(10, 20));

        assert!(
            sentinel.observe_broker_committed([("events".to_string(), 0, 10)]),
            "a frontier the pacer holds is not a commit that failed to land"
        );
    }

    #[test]
    fn a_forgotten_partition_has_nothing_to_confirm() {
        let sentinel = sentinel();
        attempt(&sentinel, "t", 0, 0, 100);
        sentinel.forget_partitions(&[TopicPartition::new("t", 0)]);
        assert!(!sentinel.observe_broker_committed([("t".to_string(), 0, 100)]));
    }

    #[test]
    fn a_disabled_sentinel_records_nothing() {
        let sentinel = sentinel();
        sentinel.set_enabled(false);
        attempt(&sentinel, "t", 0, 0, 100);
        assert!(!sentinel.observe_broker_committed([("t".to_string(), 0, 100)]));
    }
}
