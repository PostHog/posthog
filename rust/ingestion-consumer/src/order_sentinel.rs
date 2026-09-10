//! The per-key send-order sentinel and the consumer's rdkafka context. The
//! commit sentinel lives in [`crate::commit_sentinel`].
//!
//! **Per-key send order** ([`KeyOrderSentinel`]): for every routing key
//! (the Kafka message key), messages must be handed to workers in Kafka offset
//! order, and a message must never be re-sent after it was ACKed. Replays of
//! un-ACKed messages on the retry paths ([`SendKind::Resend`]: send failure →
//! deferred flush) are legal at-least-once behavior and are counted separately
//! (`ingestion_consumer_key_replays_total`) rather than flagged; the same
//! regression on a fresh assignment is a `send_below_last_sent` violation.
//! Checked in the dispatcher at assignment time — the
//! point that defines the intended per-key order — under the pin-table lock.
//! Only messages produced with a Kafka key participate: null-key production
//! (e.g. overflow rerouting) spreads a routing key across partitions,
//! deliberately forfeiting per-key order, so there is no invariant to check
//! and offsets from different partitions are not comparable. Skipped messages
//! are counted in `ingestion_consumer_key_sentinel_unkeyed_total`.
//!
//! [`SentinelContext`] is the consumer's rdkafka context: it resets sentinel
//! baselines on rebalances, where Kafka legitimately re-deals partitions and
//! the invariants must re-baseline instead of firing false positives.
//!
//! The sentinel is a pure observer: it never influences routing.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use metrics::{counter, gauge};
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::{ClientContext, Statistics, TopicPartitionList};
use tracing::{info, warn};

use crate::commit_pacer::ImmediateCommitPacer;
use crate::commit_sentinel::CommitSentinel;
use crate::types::SerializedKafkaMessage;
use common_kafka_consumer::{AssignmentEpoch, TopicOffsetLedger, TopicPartition};

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

/// How a send violated the per-key order invariant.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyOrderViolationKind {
    /// Offsets within one assigned group were not strictly ascending.
    IntraGroupDisorder,
    /// A message at or below the key's highest ACKed offset was sent again —
    /// duplicate processing of an already-acknowledged message.
    ResendAfterAck,
    /// A fresh (non-retry) send at or below the key's highest sent offset —
    /// a newer batch's send overtook an older batch's for the same key.
    SendBelowLastSent,
}

impl KeyOrderViolationKind {
    fn as_str(&self) -> &'static str {
        match self {
            KeyOrderViolationKind::IntraGroupDisorder => "intra_group_disorder",
            KeyOrderViolationKind::ResendAfterAck => "resend_after_ack",
            KeyOrderViolationKind::SendBelowLastSent => "send_below_last_sent",
        }
    }
}

/// Whether a send may legitimately repeat offsets the key has already sent.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SendKind {
    /// A first-time assignment. Fresh sends run in batch order over a key's
    /// single partition, so their offsets must only move forward; a regression
    /// is a [`KeyOrderViolationKind::SendBelowLastSent`] violation.
    Fresh,
    /// A deferred-flush retry that re-routes messages whose earlier send
    /// failed — repeating un-ACKed offsets is expected at-least-once behavior,
    /// not a violation.
    Resend,
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

    /// Record that `messages` for `routing_key` are being handed to a worker.
    /// `kind` distinguishes a fresh assignment (offsets must only move
    /// forward) from a retry-path resend (repeating un-ACKed offsets is
    /// legal). Call at assignment time, under the dispatcher's pin-table
    /// lock, so the check order matches the intended per-key send order.
    /// Null-key messages are skipped — they carry no per-key order promise
    /// (see module docs). Emits metrics and logs; returns violations for
    /// tests.
    pub fn note_sent(
        &self,
        routing_key: &str,
        messages: &[SerializedKafkaMessage],
        kind: SendKind,
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
                } else if kind == SendKind::Resend {
                    // Replay of a not-yet-ACKed range: the legal retry path
                    // (send failure → defer → flush re-routes the same messages).
                    counter!("ingestion_consumer_key_replays_total").increment(1);
                    state.last_sent = state.last_sent.max(last.offset);
                } else {
                    // A fresh send regressed: a newer batch's assignment for
                    // this key overtook an older batch's. (A rebalance racing
                    // an in-flight batch can produce a rare false positive
                    // until epoch-scoped baselines land — treat as near-zero,
                    // not hard-zero.)
                    violations.push(KeyOrderViolation {
                        kind: KeyOrderViolationKind::SendBelowLastSent,
                        routing_key: routing_key.to_string(),
                        partition: first.partition,
                        offset: first.offset,
                    });
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
/// restart-time redelivery), resets sentinel baselines around rebalances, and
/// exports librdkafka's internal statistics (see [`crate::kafka_stats`]).
pub struct SentinelContext {
    /// Where the consumer's frontiers go. Held here so the rebalance
    /// callbacks tell it which partitions leave the assignment.
    commit_sentinel: Arc<CommitSentinel>,
    key_sentinel: Arc<KeyOrderSentinel>,
    /// The offset ledger the commit path settles against. Owned here so the
    /// rebalance callbacks forget partitions on the same ledger.
    topic_offset_ledger: Arc<TopicOffsetLedger>,
    /// Advanced once per assignment callback; the gRPC transport stamps it
    /// on sub-batches so the worker's feed-order sentinel rebaselines across
    /// rebalances. Distinct from the offset ledger's generations, which move
    /// per partition and stamp offset accounting rather than stream order.
    assignment_epoch: Option<AssignmentEpoch>,
}

impl SentinelContext {
    pub fn new(
        commit_sentinel: Arc<CommitSentinel>,
        key_sentinel: Arc<KeyOrderSentinel>,
        topic_offset_ledger: Arc<TopicOffsetLedger>,
    ) -> Self {
        Self {
            commit_sentinel,
            key_sentinel,
            topic_offset_ledger,
            assignment_epoch: None,
        }
    }

    /// Wire the process-wide assignment epoch. Call before the context is
    /// handed to the Kafka consumer.
    pub fn set_assignment_epoch(&mut self, epoch: AssignmentEpoch) {
        self.assignment_epoch = Some(epoch);
    }

    /// A context with its own free-standing sentinels, ledger, and commit
    /// pacer, for tests and tools that build the Kafka consumer separately
    /// from the dispatcher.
    pub fn detached() -> Self {
        Self::new(
            Arc::new(CommitSentinel::new(ImmediateCommitPacer::new())),
            Arc::new(KeyOrderSentinel::new()),
            Arc::new(TopicOffsetLedger::new()),
        )
    }

    pub fn commit_sentinel(&self) -> Arc<CommitSentinel> {
        Arc::clone(&self.commit_sentinel)
    }

    pub fn topic_offset_ledger(&self) -> Arc<TopicOffsetLedger> {
        Arc::clone(&self.topic_offset_ledger)
    }

    /// Start a new ledger generation for every partition in `tpl`, dropping
    /// its window and any frontier it had ready to commit.
    fn forget_ledger_partitions(&self, tpl: &TopicPartitionList) {
        let elements = tpl.elements();
        self.topic_offset_ledger
            .forget_partitions(elements.iter().map(|e| (e.topic(), e.partition())));
        let topic_partitions: Vec<TopicPartition> = elements
            .iter()
            .map(|e| TopicPartition::new(e.topic(), e.partition()))
            .collect();
        self.commit_sentinel.forget_partitions(&topic_partitions);
    }
}

fn partition_names(tpl: &TopicPartitionList) -> Vec<String> {
    let elements = tpl.elements();
    let mut partitions: Vec<(&str, i32)> = elements
        .iter()
        .map(|element| (element.topic(), element.partition()))
        .collect();
    partitions.sort_unstable();
    partitions
        .into_iter()
        .map(|(topic, partition)| format!("{topic}:{partition}"))
        .collect()
}

impl ClientContext for SentinelContext {
    /// Fired on a librdkafka thread every `statistics.interval.ms`; disabled
    /// when that is 0.
    fn stats(&self, stats: Statistics) {
        crate::kafka_stats::export(&stats);
    }
}

impl ConsumerContext for SentinelContext {
    fn pre_rebalance(&self, _consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        match rebalance {
            Rebalance::Revoke(tpl) => {
                counter!("ingestion_consumer_rebalances_total", "event" => "revoke").increment(1);
                info!(
                    partitions = tpl.count(),
                    topic_partitions = ?partition_names(tpl),
                    "Rebalance: partitions revoked"
                );
                self.forget_ledger_partitions(tpl);
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
            info!(
                partitions = tpl.count(),
                topic_partitions = ?partition_names(tpl),
                "Rebalance: partitions assigned"
            );
            // An assign list names partitions that start a new assignment, so
            // any surviving ledger for them is stale. The revoke callback
            // normally dropped it already; this covers losses with no revoke
            // callback (an error rebalance, a fenced member).
            self.forget_ledger_partitions(tpl);
            if let Some(epoch) = &self.assignment_epoch {
                epoch.bump();
            }
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

    // ---- KeyOrderSentinel ----

    #[test]
    fn forward_sends_pass() {
        let sentinel = KeyOrderSentinel::new();
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh)
            .is_empty());
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn intra_group_disorder_is_detected() {
        let sentinel = KeyOrderSentinel::new();
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 2), msg_at(0, 1)], SendKind::Fresh);
        assert_eq!(violations.len(), 1);
        assert_eq!(
            violations[0].kind,
            KeyOrderViolationKind::IntraGroupDisorder
        );
    }

    #[test]
    fn replay_of_unacked_range_is_not_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        // Send failed (no ACK) → deferred flush re-sends the same messages.
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Resend)
            .is_empty());
    }

    #[test]
    fn fresh_send_below_last_sent_is_a_violation() {
        // A fresh assignment regressing below the key's sent watermark means a
        // newer batch's send overtook an older batch's — the race the
        // consumer-loop assignment ordering exists to prevent.
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)], SendKind::Fresh);
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::SendBelowLastSent);
        // The watermark still advanced: the next in-order send is clean.
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn resend_after_ack_is_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        sentinel.note_acked("t:a", 2);
        // Even the legal retry path must never repeat an ACKed offset.
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 2)], SendKind::Resend);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn older_messages_after_acked_newer_ones_are_a_violation() {
        // The exact race the deferral machinery exists to prevent: a key's
        // newer messages were sent and ACKed while its older ones were still
        // deferred — flushing the older ones now is out-of-order processing.
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 4), msg_at(0, 5)], SendKind::Fresh);
        sentinel.note_acked("t:a", 5);
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Resend);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn out_of_order_acks_only_advance_the_watermark() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        sentinel.note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)], SendKind::Fresh);
        // Sub-batch ACKs arrive in reverse HTTP-completion order.
        sentinel.note_acked("t:a", 4);
        sentinel.note_acked("t:a", 2);
        // Forward progress from the true high-water mark is still clean.
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh)
            .is_empty());
        // …and re-sending below it still fires.
        let violations = sentinel.note_sent("t:a", &[msg_at(0, 3)], SendKind::Resend);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn eviction_drops_state_and_rebaselines() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        sentinel.note_acked("t:a", 5);
        sentinel.evict("t:a");
        assert_eq!(sentinel.key_count(), 0);
        // A rebaselined key doesn't compare against evicted history.
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 6)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn clear_resets_all_keys() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        sentinel.note_sent("t:b", &[msg_at(1, 7)], SendKind::Fresh);
        sentinel.clear();
        assert_eq!(sentinel.key_count(), 0);
        // Post-rebalance redelivery of uncommitted offsets must not fire.
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 3)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn a_disabled_key_sentinel_checks_nothing_and_holds_no_state() {
        let keys = KeyOrderSentinel::new();
        keys.set_enabled(false);
        keys.note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        assert!(keys
            .note_sent("t:a", &[msg_at(0, 2), msg_at(0, 1)], SendKind::Fresh)
            .is_empty());
        assert_eq!(keys.key_count(), 0, "no state accumulates while disabled");
    }

    #[test]
    fn disabling_key_sentinel_clears_stale_watermarks() {
        let keys = KeyOrderSentinel::new();
        keys.note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        keys.note_acked("t:a", 5);
        keys.set_enabled(false);
        keys.set_enabled(true);
        // Re-enable rebaselines: no comparison against pre-disable history.
        assert!(keys
            .note_sent("t:a", &[msg_at(0, 3)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn partition_move_rebaselines() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.note_sent("t:a", &[msg_at(0, 100)], SendKind::Fresh);
        // Same key on a different partition: offsets aren't comparable.
        assert!(sentinel
            .note_sent("t:a", &[msg_at(3, 1)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn null_key_messages_are_ignored() {
        let sentinel = KeyOrderSentinel::new();
        // Null-key production round-robins a key across partitions; there is
        // no per-key order to check, even when offsets regress across sends.
        assert!(sentinel
            .note_sent("t:a", &[unkeyed_msg_at(1, 5000)], SendKind::Fresh)
            .is_empty());
        assert_eq!(sentinel.key_count(), 0, "unkeyed sends hold no state");
        assert!(sentinel
            .note_sent("t:a", &[unkeyed_msg_at(0, 3)], SendKind::Fresh)
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
            .note_sent(
                "t:a",
                &[msg_at(0, 100), unkeyed_msg_at(1, 5000)],
                SendKind::Fresh
            )
            .is_empty());
        sentinel.note_acked("t:a", 100);
        assert!(sentinel
            .note_sent("t:a", &[msg_at(0, 101)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn partition_names_sort_by_topic_then_partition_number() {
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition("overflow", 2);
        tpl.add_partition("events", 10);
        tpl.add_partition("events", 9);

        assert_eq!(
            partition_names(&tpl),
            vec!["events:9", "events:10", "overflow:2"]
        );
    }
}
