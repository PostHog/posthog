//! The commit sentinel: an always-on observer that turns the consumer's
//! commit guarantee into alertable metrics.
//!
//! **Commit order**: for every topic-partition, offsets must be committed
//! contiguously and monotonically — each span's first offset must equal the
//! previously committed offset (no skips), and the committed offset must
//! never move backwards (no out-of-order commits). Violations increment
//! `ingestion_consumer_commit_violations_total{kind}` and log the offending
//! offsets. `ingestion_consumer_commits_checked_total` is the denominator: the
//! guarantee holds while it grows and the violation counter stays flat.
//!
//! **Commit confirmation**: "commits are actually made" cannot be observed via
//! `ConsumerContext::commit_callback` — librdkafka drops the result of manual
//! async commits (see the note on [`crate::order_sentinel::SentinelContext`]).
//! Instead the commit monitor periodically fetches the group's
//! broker-committed offsets and feeds [`CommitSentinel::observe_broker_committed`],
//! which emits `ingestion_consumer_broker_committed_offset` and
//! `ingestion_consumer_commit_confirmation_lag` gauges and stamps
//! `ingestion_consumer_last_successful_commit_timestamp_seconds` on progress.
//!
//! Rebalances reset the baselines, where Kafka legitimately re-deals
//! partitions and the invariant must re-baseline instead of firing false
//! positives. The sentinel is a pure observer: it never influences commits.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use common_kafka_consumer::TopicPartition;
use metrics::{counter, gauge};
use tracing::warn;

use crate::order_sentinel::OffsetSpan;

/// How a commit violated the contiguous-monotonic invariant.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CommitViolationKind {
    /// The batch starts past the previously committed offset — the offsets in
    /// between were never part of a committed batch (skipped messages).
    Gap,
    /// The whole batch lies at or behind the committed offset — the commit
    /// moves the partition backwards.
    OutOfOrder,
    /// The batch partially re-covers already-committed offsets.
    Overlap,
}

impl CommitViolationKind {
    fn as_str(&self) -> &'static str {
        match self {
            CommitViolationKind::Gap => "gap",
            CommitViolationKind::OutOfOrder => "out_of_order",
            CommitViolationKind::Overlap => "overlap",
        }
    }
}

/// One detected commit-order violation, returned for tests and logged.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CommitViolation {
    pub kind: CommitViolationKind,
    pub topic: String,
    pub partition: i32,
    /// The partition's committed offset (Kafka "next to read") before this batch.
    pub prev_committed: i64,
    pub span: OffsetSpan,
}

/// Per-partition commit tracking: what this process asked Kafka to commit
/// (attempted) and what the broker has confirmed as the group's committed
/// offset (observed by the commit monitor via OffsetFetch).
#[derive(Default, Clone, Copy)]
struct PartitionCommits {
    /// The offset value last submitted for commit (Kafka "next to read").
    attempted: Option<i64>,
    /// The broker-confirmed committed offset from the last monitor poll.
    confirmed: Option<i64>,
}

/// Tracks the last committed offset per topic-partition and checks each new
/// commit for contiguity and monotonicity. The first commit after a partition
/// is (re)assigned establishes a baseline and is never a violation — earlier
/// offsets may have been committed by another consumer in the group.
///
/// Caveat: legitimate offset gaps exist on topics with transactional producers
/// (control records consume offsets). The ingestion topics are produced by
/// capture without transactions, so a gap here is a real skip.
///
/// Because commits use `CommitMode::Async` and librdkafka silently drops the
/// result of manual async commits (no conf-level `offset_commit_cb` is ever
/// registered by rust-rdkafka, so `ConsumerContext::commit_callback` never
/// fires for them), commit *success* is verified out of band: the consumer's
/// commit monitor periodically fetches the group's broker-committed offsets
/// and feeds them to [`CommitSentinel::observe_broker_committed`].
pub struct CommitSentinel {
    partitions: Mutex<HashMap<(String, i32), PartitionCommits>>,
    /// Kill switch (`CONSUMER_ORDER_SENTINEL_ENABLED`). When off, checks
    /// no-op and no state accumulates.
    enabled: AtomicBool,
}

impl Default for CommitSentinel {
    fn default() -> Self {
        Self {
            partitions: Mutex::new(HashMap::new()),
            enabled: AtomicBool::new(true),
        }
    }
}

impl CommitSentinel {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set_enabled(&self, enabled: bool) {
        self.enabled.store(enabled, Ordering::Relaxed);
    }

    /// Check a batch's offset spans against the previous commit per partition,
    /// then advance the tracked committed offset to `span.last + 1`. Emits
    /// metrics and logs; returns the violations for tests.
    pub fn check_commit<'a>(
        &self,
        spans: impl IntoIterator<Item = (&'a TopicPartition, &'a OffsetSpan)>,
    ) -> Vec<CommitViolation> {
        if !self.enabled.load(Ordering::Relaxed) {
            return Vec::new();
        }
        let mut partitions = self.partitions.lock().unwrap();
        let mut violations = Vec::new();

        for (topic_partition, span) in spans {
            counter!("ingestion_consumer_commits_checked_total").increment(1);

            let topic = &topic_partition.topic;
            let partition = &topic_partition.partition;
            let state = partitions.entry((topic.clone(), *partition)).or_default();
            if let Some(prev) = state.attempted {
                let kind = if span.first == prev {
                    None
                } else if span.first > prev {
                    Some(CommitViolationKind::Gap)
                } else if span.last < prev {
                    Some(CommitViolationKind::OutOfOrder)
                } else {
                    Some(CommitViolationKind::Overlap)
                };

                if let Some(kind) = kind {
                    counter!(
                        "ingestion_consumer_commit_violations_total",
                        "kind" => kind.as_str(),
                    )
                    .increment(1);
                    warn!(
                        kind = kind.as_str(),
                        topic = %topic,
                        partition = *partition,
                        prev_committed = prev,
                        batch_first = span.first,
                        batch_last = span.last,
                        "Commit order violation"
                    );
                    violations.push(CommitViolation {
                        kind,
                        topic: topic.clone(),
                        partition: *partition,
                        prev_committed: prev,
                        span: *span,
                    });
                }
            }

            state.attempted = Some(span.last + 1);
            gauge!(
                "ingestion_consumer_committed_offset",
                "topic" => topic.clone(),
                "partition" => partition.to_string(),
            )
            .set((span.last + 1) as f64);
        }

        violations
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

    /// Drop the baselines for revoked partitions so the next commit after a
    /// re-assignment baselines instead of reporting a false gap/overlap
    /// (another group member may have committed in between).
    pub fn forget_partitions<'a>(&self, revoked: impl IntoIterator<Item = (&'a str, i32)>) {
        let mut partitions = self.partitions.lock().unwrap();
        for (topic, partition) in revoked {
            let forgotten = partitions.remove(&(topic.to_string(), partition));
            if forgotten.is_some_and(|state| state.attempted.is_some()) {
                let topic: Arc<str> = Arc::from(topic);
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
    use super::*;

    fn spans(entries: &[(&str, i32, i64, i64)]) -> HashMap<TopicPartition, OffsetSpan> {
        entries
            .iter()
            .map(|(topic, partition, first, last)| {
                (
                    TopicPartition::new(*topic, *partition),
                    OffsetSpan {
                        first: *first,
                        last: *last,
                    },
                )
            })
            .collect()
    }

    // ---- CommitSentinel ----

    #[test]
    fn contiguous_commits_pass() {
        let sentinel = CommitSentinel::new();
        assert!(
            sentinel.check_commit(&spans(&[("t", 0, 0, 99)])).is_empty(),
            "first commit baselines"
        );
        assert!(
            sentinel
                .check_commit(&spans(&[("t", 0, 100, 149)]))
                .is_empty(),
            "next batch starts exactly at the committed offset"
        );
    }

    #[test]
    fn commit_gap_is_detected() {
        let sentinel = CommitSentinel::new();
        sentinel.check_commit(&spans(&[("t", 0, 0, 99)]));
        // Offsets 100..=104 were never committed — the batch skipped them.
        let violations = sentinel.check_commit(&spans(&[("t", 0, 105, 150)]));
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, CommitViolationKind::Gap);
        assert_eq!(violations[0].prev_committed, 100);
    }

    #[test]
    fn commit_regression_is_out_of_order() {
        let sentinel = CommitSentinel::new();
        sentinel.check_commit(&spans(&[("t", 0, 0, 99)]));
        let violations = sentinel.check_commit(&spans(&[("t", 0, 10, 50)]));
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, CommitViolationKind::OutOfOrder);
    }

    #[test]
    fn partial_recommit_is_overlap() {
        let sentinel = CommitSentinel::new();
        sentinel.check_commit(&spans(&[("t", 0, 0, 99)]));
        let violations = sentinel.check_commit(&spans(&[("t", 0, 90, 150)]));
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, CommitViolationKind::Overlap);
    }

    #[test]
    fn partitions_are_tracked_independently() {
        let sentinel = CommitSentinel::new();
        sentinel.check_commit(&spans(&[("t", 0, 0, 99), ("t", 1, 0, 9)]));
        // Partition 0 continues cleanly; partition 1 skips 10..=19.
        let violations = sentinel.check_commit(&spans(&[("t", 0, 100, 120), ("t", 1, 20, 30)]));
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].partition, 1);
        assert_eq!(violations[0].kind, CommitViolationKind::Gap);
    }

    #[test]
    fn broker_observation_baselines_then_tracks_progress() {
        let sentinel = CommitSentinel::new();
        sentinel.check_commit(&spans(&[("t", 0, 0, 99)])); // attempted next = 100
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
        let sentinel = CommitSentinel::new();
        sentinel.check_commit(&spans(&[("t", 0, 0, 99), ("t", 1, 0, 9)]));
        sentinel.observe_broker_committed([("t".to_string(), 0, 100), ("t".to_string(), 1, 5)]);
        // Partition 0 fully confirmed but partition 1 stuck below attempted and
        // not advancing: not progress.
        assert!(!sentinel
            .observe_broker_committed([("t".to_string(), 0, 100), ("t".to_string(), 1, 5)]));
    }

    #[test]
    fn forgotten_partition_rebaselines_without_violation() {
        let sentinel = CommitSentinel::new();
        sentinel.check_commit(&spans(&[("t", 0, 0, 99)]));
        sentinel.forget_partitions([("t", 0)]);
        // After revoke + re-assign another consumer may have committed past us;
        // a non-contiguous first commit must baseline, not fire.
        assert!(sentinel
            .check_commit(&spans(&[("t", 0, 500, 599)]))
            .is_empty());
    }

    #[test]
    fn a_disabled_sentinel_checks_nothing() {
        let commit = CommitSentinel::new();
        commit.set_enabled(false);
        commit.check_commit(&spans(&[("t", 0, 0, 99)]));
        // A blatant regression passes: the kill switch disarms the check.
        assert!(commit.check_commit(&spans(&[("t", 0, 10, 50)])).is_empty());
    }
}
