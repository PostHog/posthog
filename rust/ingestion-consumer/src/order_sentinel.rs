//! Always-on ordering sentinels: cheap invariant checkers that turn the
//! consumer's two core guarantees into alertable metrics.
//!
//! **Commit order** ([`CommitSentinel`]): for every topic-partition, offsets
//! must be committed contiguously and monotonically — each batch's first
//! offset must equal the previously committed offset (no skips), and the
//! committed offset must never move backwards (no out-of-order commits).
//! Checked at commit time in the consumer loop; violations increment
//! `ingestion_consumer_commit_violations_total{kind}` and log the offending
//! offsets. `ingestion_consumer_commits_checked_total` is the denominator: the
//! guarantee holds while it grows and the violation counter stays flat.
//!
//! **Per-key send order** ([`KeyOrderSentinel`]): for every routing key
//! (`token:distinct_id`), messages must be handed to workers in Kafka offset
//! order, and a message must never be re-sent after it was ACKed. Replays of
//! un-ACKed messages (send failure → deferred flush) are legal at-least-once
//! behavior and are counted separately (`ingestion_consumer_key_replays_total`)
//! rather than flagged. Checked in the dispatcher at assignment time — the
//! point that defines the intended per-key order — under the pin-table lock.
//! Only messages produced with a Kafka key participate: null-key production
//! (e.g. overflow rerouting) spreads a routing key across partitions,
//! deliberately forfeiting per-key order, so there is no invariant to check
//! and offsets from different partitions are not comparable. Skipped messages
//! are counted in `ingestion_consumer_key_sentinel_unkeyed_total`.
//!
//! **Commit confirmation**: "commits are actually made" cannot be observed via
//! `ConsumerContext::commit_callback` — librdkafka drops the result of manual
//! async commits (see the note on [`SentinelContext`]). Instead the consumer's
//! commit monitor periodically fetches the group's broker-committed offsets and
//! feeds [`CommitSentinel::observe_broker_committed`], which emits
//! `ingestion_consumer_broker_committed_offset` and
//! `ingestion_consumer_commit_confirmation_lag` gauges and stamps
//! `ingestion_consumer_last_successful_commit_timestamp_seconds` on progress.
//!
//! [`SentinelContext`] is the consumer's rdkafka context: it resets sentinel
//! baselines on rebalances, where Kafka legitimately re-deals partitions and
//! both invariants must re-baseline instead of firing false positives.
//!
//! The sentinels are pure observers: they never influence routing or commits.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use metrics::{counter, gauge};
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::ClientContext;
use tracing::{info, warn};

use crate::types::SerializedKafkaMessage;

/// The first and last Kafka offsets a batch holds for one topic-partition.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OffsetSpan {
    pub first: i64,
    pub last: i64,
}

impl OffsetSpan {
    pub fn new(offset: i64) -> Self {
        Self {
            first: offset,
            last: offset,
        }
    }

    /// Widen the span to include `offset`.
    pub fn extend(&mut self, offset: i64) {
        self.first = self.first.min(offset);
        self.last = self.last.max(offset);
    }
}

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
    pub fn check_commit(&self, spans: &HashMap<(String, i32), OffsetSpan>) -> Vec<CommitViolation> {
        if !self.enabled.load(Ordering::Relaxed) {
            return Vec::new();
        }
        let mut partitions = self.partitions.lock().unwrap();
        let mut violations = Vec::new();

        for ((topic, partition), span) in spans {
            counter!("ingestion_consumer_commits_checked_total").increment(1);

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
            partitions.remove(&(topic.to_string(), partition));
        }
    }
}

/// How a send violated the per-key order invariant.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyOrderViolationKind {
    /// Offsets within one assigned group were not strictly ascending.
    IntraGroupDisorder,
    /// A message at or below the key's highest ACKed offset was sent again —
    /// duplicate processing of an already-acknowledged message.
    ResendAfterAck,
}

impl KeyOrderViolationKind {
    fn as_str(&self) -> &'static str {
        match self {
            KeyOrderViolationKind::IntraGroupDisorder => "intra_group_disorder",
            KeyOrderViolationKind::ResendAfterAck => "resend_after_ack",
        }
    }
}

/// One detected per-key order violation, returned for tests and logged.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KeyOrderViolation {
    pub kind: KeyOrderViolationKind,
    pub routing_key: String,
    pub partition: i32,
    pub offset: i64,
}

struct KeyState {
    partition: i32,
    /// Highest offset ever handed to a worker for this key.
    last_sent: i64,
    /// Highest offset a worker has ACKed for this key.
    last_acked: Option<i64>,
}

/// Tracks per-routing-key send/ACK progress and checks every assignment
/// against it. State lives exactly as long as the key's pin: the dispatcher
/// evicts it when the pin is evicted (all sends resolved, nothing deferred),
/// so the map is bounded by in-flight work — the same bound as the pin table.
///
/// A key whose state was evicted rebaselines on its next send. That is sound
/// within a process: the key's messages arrive from its single partition in
/// offset order, and eviction requires every earlier send to have resolved.
pub struct KeyOrderSentinel {
    keys: Mutex<HashMap<String, KeyState>>,
    /// Kill switch (`CONSUMER_ORDER_SENTINEL_ENABLED`). When off, checks
    /// no-op and no state accumulates.
    enabled: AtomicBool,
}

impl Default for KeyOrderSentinel {
    fn default() -> Self {
        Self {
            keys: Mutex::new(HashMap::new()),
            enabled: AtomicBool::new(true),
        }
    }
}

impl KeyOrderSentinel {
    pub fn new() -> Self {
        Self::default()
    }

    /// Toggle the sentinel. Disabling clears existing state so a later
    /// re-enable rebaselines instead of comparing against stale watermarks.
    pub fn set_enabled(&self, enabled: bool) {
        self.enabled.store(enabled, Ordering::Relaxed);
        if !enabled {
            self.clear();
        }
    }

    /// Record that `messages` for `routing_key` are being handed to a worker
    /// (fresh assignment or deferred flush). Call at assignment time, under the
    /// dispatcher's pin-table lock, so the check order matches the intended
    /// per-key send order. Null-key messages are skipped — they carry no
    /// per-key order promise (see module docs). Emits metrics and logs;
    /// returns violations for tests.
    pub fn note_sent(
        &self,
        routing_key: &str,
        messages: &[SerializedKafkaMessage],
    ) -> Vec<KeyOrderViolation> {
        if !self.enabled.load(Ordering::Relaxed) {
            return Vec::new();
        }
        let keyed: Vec<&SerializedKafkaMessage> =
            messages.iter().filter(|m| m.key.is_some()).collect();
        let unkeyed = messages.len() - keyed.len();
        if unkeyed > 0 {
            counter!("ingestion_consumer_key_sentinel_unkeyed_total").increment(unkeyed as u64);
        }
        let Some(first) = keyed.first() else {
            return Vec::new();
        };
        let last = keyed.last().expect("non-empty");
        let mut violations = Vec::new();

        // Offsets within an assigned group must be strictly ascending: groups
        // are built in batch order, and a batch preserves partition order.
        for pair in keyed.windows(2) {
            if pair[1].partition == pair[0].partition && pair[1].offset <= pair[0].offset {
                violations.push(KeyOrderViolation {
                    kind: KeyOrderViolationKind::IntraGroupDisorder,
                    routing_key: routing_key.to_string(),
                    partition: pair[1].partition,
                    offset: pair[1].offset,
                });
            }
        }

        let mut keys = self.keys.lock().unwrap();
        match keys.get_mut(routing_key) {
            None => {
                keys.insert(
                    routing_key.to_string(),
                    KeyState {
                        partition: first.partition,
                        last_sent: last.offset,
                        last_acked: None,
                    },
                );
            }
            Some(state) => {
                if state.partition != first.partition {
                    // With null-key messages filtered out, a key's messages all
                    // come from the partition its Kafka key hashes to; a move
                    // mid-flight is a real anomaly (e.g. partition-count
                    // change). Count it and rebaseline rather than comparing
                    // offsets across partitions, which would be meaningless.
                    counter!("ingestion_consumer_key_partition_moves_total").increment(1);
                    *state = KeyState {
                        partition: first.partition,
                        last_sent: last.offset,
                        last_acked: None,
                    };
                } else if first.offset > state.last_sent {
                    // Normal forward progress.
                    state.last_sent = last.offset;
                } else if state.last_acked.is_some_and(|acked| first.offset <= acked) {
                    violations.push(KeyOrderViolation {
                        kind: KeyOrderViolationKind::ResendAfterAck,
                        routing_key: routing_key.to_string(),
                        partition: first.partition,
                        offset: first.offset,
                    });
                    state.last_sent = state.last_sent.max(last.offset);
                } else {
                    // Replay of a not-yet-ACKed range: the legal retry path
                    // (send failure → defer → flush re-routes the same messages).
                    counter!("ingestion_consumer_key_replays_total").increment(1);
                    state.last_sent = state.last_sent.max(last.offset);
                }
            }
        }
        let key_count = keys.len();
        drop(keys);
        gauge!("ingestion_consumer_key_sentinel_keys").set(key_count as f64);

        for violation in &violations {
            counter!(
                "ingestion_consumer_key_order_violations_total",
                "kind" => violation.kind.as_str(),
            )
            .increment(1);
            warn!(
                kind = violation.kind.as_str(),
                routing_key = %violation.routing_key,
                partition = violation.partition,
                offset = violation.offset,
                "Per-key send order violation"
            );
        }

        violations
    }

    /// Record that a worker ACKed this key's messages up to `max_offset`.
    /// ACKs may arrive out of order across concurrent sub-batches (HTTP
    /// completion order), so this only ever advances the high-water mark.
    pub fn note_acked(&self, routing_key: &str, max_offset: i64) {
        if !self.enabled.load(Ordering::Relaxed) {
            return;
        }
        let mut keys = self.keys.lock().unwrap();
        if let Some(state) = keys.get_mut(routing_key) {
            state.last_acked = Some(state.last_acked.map_or(max_offset, |a| a.max(max_offset)));
        }
    }

    /// Drop a key's state. Call when its pin is evicted — every send has
    /// resolved and nothing is deferred, so there is nothing left to order
    /// against and future offsets are necessarily higher.
    pub fn evict(&self, routing_key: &str) {
        if !self.enabled.load(Ordering::Relaxed) {
            return;
        }
        let mut keys = self.keys.lock().unwrap();
        keys.remove(routing_key);
        let key_count = keys.len();
        drop(keys);
        gauge!("ingestion_consumer_key_sentinel_keys").set(key_count as f64);
    }

    /// Drop all state. Called on rebalance: partitions may move to another
    /// consumer and back, legitimately replaying uncommitted offsets, so every
    /// baseline is stale.
    pub fn clear(&self) {
        self.keys.lock().unwrap().clear();
        gauge!("ingestion_consumer_key_sentinel_keys").set(0.0);
    }

    /// Number of tracked keys (bounded by in-flight work; exposed for tests).
    pub fn key_count(&self) -> usize {
        self.keys.lock().unwrap().len()
    }
}

/// The consumer's rdkafka context: observes async commit results (a
/// fire-and-forget `CommitMode::Async` failure is otherwise invisible until
/// restart-time redelivery) and resets sentinel baselines around rebalances.
pub struct SentinelContext {
    commit_sentinel: Arc<CommitSentinel>,
    key_sentinel: Arc<KeyOrderSentinel>,
}

impl SentinelContext {
    pub fn new(commit_sentinel: Arc<CommitSentinel>, key_sentinel: Arc<KeyOrderSentinel>) -> Self {
        Self {
            commit_sentinel,
            key_sentinel,
        }
    }

    /// A context with its own free-standing sentinels, for tests and tools
    /// that build the Kafka consumer separately from the dispatcher.
    pub fn detached() -> Self {
        Self::new(
            Arc::new(CommitSentinel::new()),
            Arc::new(KeyOrderSentinel::new()),
        )
    }

    pub fn commit_sentinel(&self) -> Arc<CommitSentinel> {
        Arc::clone(&self.commit_sentinel)
    }
}

impl ClientContext for SentinelContext {}

impl ConsumerContext for SentinelContext {
    fn pre_rebalance(&self, _consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        match rebalance {
            Rebalance::Revoke(tpl) => {
                counter!("ingestion_consumer_rebalances_total", "event" => "revoke").increment(1);
                info!(partitions = tpl.count(), "Rebalance: partitions revoked");
                self.commit_sentinel
                    .forget_partitions(tpl.elements().iter().map(|e| (e.topic(), e.partition())));
                // Revoked partitions may be replayed by another consumer (or by
                // us after re-assignment) from the last commit — every per-key
                // baseline is stale.
                self.key_sentinel.clear();
            }
            Rebalance::Assign(_) => {}
            Rebalance::Error(err) => {
                counter!("ingestion_consumer_rebalances_total", "event" => "error").increment(1);
                warn!(error = %err, "Rebalance error");
            }
        }
    }

    fn post_rebalance(&self, _consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        if let Rebalance::Assign(tpl) = rebalance {
            counter!("ingestion_consumer_rebalances_total", "event" => "assign").increment(1);
            info!(partitions = tpl.count(), "Rebalance: partitions assigned");
        }
    }

    // NOTE: `ConsumerContext::commit_callback` is deliberately not implemented.
    // librdkafka only propagates a commit result to the application when a
    // conf-level `offset_commit_cb` is registered (rust-rdkafka never does) or
    // when the commit is synchronous (a replyq is attached); manual async
    // commits silently drop their result (`rd_kafka_cgrp_propagate_commit_result`).
    // Commit success is instead verified by the consumer's commit monitor via
    // `CommitSentinel::observe_broker_committed`.
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spans(entries: &[(&str, i32, i64, i64)]) -> HashMap<(String, i32), OffsetSpan> {
        entries
            .iter()
            .map(|(topic, partition, first, last)| {
                (
                    (topic.to_string(), *partition),
                    OffsetSpan {
                        first: *first,
                        last: *last,
                    },
                )
            })
            .collect()
    }

    fn msg_at(partition: i32, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition,
            offset,
            timestamp: 0,
            key: Some("t:a".to_string()),
            value: None,
            headers: HashMap::new(),
        }
    }

    fn unkeyed_msg_at(partition: i32, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            key: None,
            ..msg_at(partition, offset)
        }
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

    // ---- KeyOrderSentinel ----

    #[test]
    fn forward_sends_pass() {
        let sentinel = KeyOrderSentinel::new();
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)])
            .is_empty());
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)])
            .is_empty());
    }

    #[test]
    fn intra_group_disorder_is_detected() {
        let sentinel = KeyOrderSentinel::new();
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 2), msg_at(0, 1)]);
        assert_eq!(violations.len(), 1);
        assert_eq!(
            violations[0].kind,
            KeyOrderViolationKind::IntraGroupDisorder
        );
    }

    #[test]
    fn replay_of_unacked_range_is_not_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)]);
        // Send failed (no ACK) → deferred flush re-sends the same messages.
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)])
            .is_empty());
    }

    #[test]
    fn resend_after_ack_is_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)]);
        sentinel.note_acked("t:a", 2);
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 2)]);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn older_messages_after_acked_newer_ones_are_a_violation() {
        // The exact race the deferral machinery exists to prevent: a key's
        // newer messages were sent and ACKed while its older ones were still
        // deferred — flushing the older ones now is out-of-order processing.
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 4), msg_at(0, 5)]);
        sentinel.note_acked("t:a", 5);
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)]);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn out_of_order_acks_only_advance_the_watermark() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)]);
        sentinel.note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)]);
        // Sub-batch ACKs arrive in reverse HTTP-completion order.
        sentinel.note_acked("t:a", 4);
        sentinel.note_acked("t:a", 2);
        // Forward progress from the true high-water mark is still clean.
        assert!(sentinel.note_sent("t:a", &[msg_at(0, 5)]).is_empty());
        // …and re-sending below it still fires.
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 3)]);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn eviction_drops_state_and_rebaselines() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 5)]);
        sentinel.note_acked("t:a", 5);
        sentinel.evict("t:a");
        assert_eq!(sentinel.key_count(), 0);
        // A rebaselined key doesn't compare against evicted history.
        assert!(sentinel.note_sent("t:a", &[msg_at(0, 6)]).is_empty());
    }

    #[test]
    fn clear_resets_all_keys() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 5)]);
        sentinel.note_sent("t:b", &[msg_at(1, 7)]);
        sentinel.clear();
        assert_eq!(sentinel.key_count(), 0);
        // Post-rebalance redelivery of uncommitted offsets must not fire.
        assert!(sentinel.note_sent("t:a", &[msg_at(0, 3)]).is_empty());
    }

    #[test]
    fn disabled_sentinels_check_nothing_and_hold_no_state() {
        let commit = CommitSentinel::new();
        commit.set_enabled(false);
        commit.check_commit(&spans(&[("t", 0, 0, 99)]));
        // A blatant regression passes: the kill switch disarms the check.
        assert!(commit.check_commit(&spans(&[("t", 0, 10, 50)])).is_empty());

        let keys = KeyOrderSentinel::new();
        keys.set_enabled(false);
        keys.note_sent("t:a", &[msg_at(0, 5)]);
        assert!(keys
            .note_sent("t:a", &[msg_at(0, 2), msg_at(0, 1)])
            .is_empty());
        assert_eq!(keys.key_count(), 0, "no state accumulates while disabled");
    }

    #[test]
    fn disabling_key_sentinel_clears_stale_watermarks() {
        let keys = KeyOrderSentinel::new();
        keys.note_sent("t:a", &[msg_at(0, 5)]);
        keys.note_acked("t:a", 5);
        keys.set_enabled(false);
        keys.set_enabled(true);
        // Re-enable rebaselines: no comparison against pre-disable history.
        assert!(keys.note_sent("t:a", &[msg_at(0, 3)]).is_empty());
    }

    #[test]
    fn partition_move_rebaselines() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 100)]);
        // Same key on a different partition: offsets aren't comparable.
        assert!(sentinel.note_sent("t:a", &[msg_at(3, 1)]).is_empty());
    }

    #[test]
    fn null_key_messages_are_ignored() {
        let sentinel = KeyOrderSentinel::new();
        // Null-key production round-robins a key across partitions; there is
        // no per-key order to check, even when offsets regress across sends.
        assert!(sentinel
            .note_sent("t:a", &[unkeyed_msg_at(1, 5000)])
            .is_empty());
        assert_eq!(sentinel.key_count(), 0, "unkeyed sends hold no state");
        assert!(sentinel
            .note_sent("t:a", &[unkeyed_msg_at(0, 3)])
            .is_empty());
    }

    #[test]
    fn null_key_offsets_do_not_inflate_watermarks() {
        // A mixed group (keyed traffic that overflowed mid-stream): the
        // unkeyed message's offset comes from another partition and must not
        // advance the key's send/ACK watermarks — otherwise the next keyed
        // send would fire a false resend_after_ack.
        let sentinel = KeyOrderSentinel::new();
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 100), unkeyed_msg_at(1, 5000)])
            .is_empty());
        sentinel.note_acked("t:a", 100);
        assert!(sentinel.note_sent("t:a", &[msg_at(0, 101)]).is_empty());
    }
}
