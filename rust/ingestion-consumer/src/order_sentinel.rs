//! The per-key send-order sentinel.
//!
//! For every routing key (the Kafka message key), messages must go to
//! workers in offset order, and an ACKed message must never be sent again.
//! [`SendKind::Resend`] may repeat un-ACKed offsets. The batcher checks each
//! send as it begins it. Null-key messages are skipped: null-key production
//! spreads a key across partitions, so it has no per-key order.
//!
//! The sentinel only observes: it never changes routing.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use metrics::{counter, gauge};
use tracing::warn;

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

    pub fn extend(&mut self, offset: i64) {
        self.first = self.first.min(offset);
        self.last = self.last.max(offset);
    }
}

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
    /// A replay of messages whose earlier send failed or came back
    /// unfinished. Repeating un-ACKed offsets is expected at-least-once
    /// behavior, not a violation.
    Resend,
}

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

/// Tracks per-routing-key send/ACK progress and checks every send against
/// it. State lives exactly as long as the batcher tracks the key: the batcher
/// evicts it when the key has nothing queued or in flight, so the map is
/// bounded by the batcher's key table.
///
/// A key whose state was evicted rebaselines on its next send. That is sound
/// within a process: the key's messages arrive from its single partition in
/// offset order, and eviction requires every earlier send to have resolved.
pub struct KeyOrderSentinel {
    /// Keyed by customer-chosen routing keys, so the hasher is seeded per
    /// map to resist collision flooding.
    keys: Mutex<HashMap<Arc<str>, KeyState, ahash::RandomState>>,
    enabled: AtomicBool,
}

impl Default for KeyOrderSentinel {
    fn default() -> Self {
        Self {
            keys: Mutex::new(HashMap::default()),
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

    /// Takes the lock once for several calls and sets the key-count gauge
    /// once, when the batch drops.
    pub fn batch(&self) -> SentinelBatch<'_> {
        let keys = self
            .enabled
            .load(Ordering::Relaxed)
            .then(|| self.keys.lock().unwrap());
        SentinelBatch { keys }
    }

    /// Drop all state. Called on rebalance: partitions may move to another
    /// consumer and back, legitimately replaying uncommitted offsets, so every
    /// baseline is stale.
    pub fn clear(&self) {
        self.keys.lock().unwrap().clear();
        gauge!("ingestion_consumer_key_sentinel_keys").set(0.0);
    }

    pub fn key_count(&self) -> usize {
        self.keys.lock().unwrap().len()
    }
}
/// A routing key the sentinel looks up as `&str` and stores as `Arc<str>`,
/// so a caller that already shares its keys stores them without a copy.
pub trait SentinelKey {
    fn as_key(&self) -> &str;
    fn to_shared(&self) -> Arc<str>;
}

impl SentinelKey for str {
    fn as_key(&self) -> &str {
        self
    }

    fn to_shared(&self) -> Arc<str> {
        Arc::from(self)
    }
}

impl SentinelKey for String {
    fn as_key(&self) -> &str {
        self
    }

    fn to_shared(&self) -> Arc<str> {
        Arc::from(self.as_str())
    }
}

impl SentinelKey for Arc<str> {
    fn as_key(&self) -> &str {
        self
    }

    fn to_shared(&self) -> Arc<str> {
        Arc::clone(self)
    }
}

/// A run of sentinel calls under one lock. Disabled, every call is a no-op.
pub struct SentinelBatch<'a> {
    keys: Option<MutexGuard<'a, HashMap<Arc<str>, KeyState, ahash::RandomState>>>,
}

impl SentinelBatch<'_> {
    /// Record that `messages` for `routing_key` go to a worker now. Call in the
    /// intended per-key send order. Skips null-key messages. Emits metrics and
    /// logs; returns the violations for tests.
    pub fn note_sent(
        &mut self,
        key: &(impl SentinelKey + ?Sized),
        messages: &[SerializedKafkaMessage],
        kind: SendKind,
    ) -> Vec<KeyOrderViolation> {
        let Some(keys) = self.keys.as_mut() else {
            return Vec::new();
        };
        let routing_key = key.as_key();
        let mut violations = Vec::new();
        let mut first: Option<&SerializedKafkaMessage> = None;
        let mut last: Option<&SerializedKafkaMessage> = None;
        // The watermark tracks one partition; a key run merged across
        // partitions must not mix another partition's offset into it.
        let mut last_on_first_partition = None;
        let mut unkeyed = 0usize;
        for message in messages {
            if message.key.is_none() {
                unkeyed += 1;
                continue;
            }
            // Offsets within an assigned group must be strictly ascending:
            // groups are built in batch order, and a batch preserves
            // partition order.
            if let Some(previous) = last {
                if message.partition == previous.partition && message.offset <= previous.offset {
                    violations.push(KeyOrderViolation {
                        kind: KeyOrderViolationKind::IntraGroupDisorder,
                        routing_key: routing_key.to_string(),
                        partition: message.partition,
                        offset: message.offset,
                    });
                }
            }
            let first = first.get_or_insert(message);
            if message.partition == first.partition {
                last_on_first_partition = Some(message.offset);
            }
            last = Some(message);
        }
        if unkeyed > 0 {
            counter!("ingestion_consumer_key_sentinel_unkeyed_total").increment(unkeyed as u64);
        }
        let (Some(first), Some(last_sent)) = (first, last_on_first_partition) else {
            return violations;
        };

        match keys.get_mut(routing_key) {
            None => {
                keys.insert(
                    key.to_shared(),
                    KeyState {
                        partition: first.partition,
                        last_sent,
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
                        last_sent,
                        last_acked: None,
                    };
                } else if first.offset > state.last_sent {
                    state.last_sent = last_sent;
                } else if state.last_acked.is_some_and(|acked| first.offset <= acked) {
                    violations.push(KeyOrderViolation {
                        kind: KeyOrderViolationKind::ResendAfterAck,
                        routing_key: routing_key.to_string(),
                        partition: first.partition,
                        offset: first.offset,
                    });
                    state.last_sent = state.last_sent.max(last_sent);
                } else if kind == SendKind::Resend {
                    counter!("ingestion_consumer_key_replays_total").increment(1);
                    state.last_sent = state.last_sent.max(last_sent);
                } else {
                    // A fresh send regressed: a newer send for this key overtook an older one.
                    violations.push(KeyOrderViolation {
                        kind: KeyOrderViolationKind::SendBelowLastSent,
                        routing_key: routing_key.to_string(),
                        partition: first.partition,
                        offset: first.offset,
                    });
                    state.last_sent = state.last_sent.max(last_sent);
                }
            }
        }

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

    /// Record that a worker ACKed this key's messages up to `max_offset`. ACKs
    /// from different workers can arrive out of order, so the mark only advances.
    pub fn note_acked(&mut self, routing_key: &str, max_offset: i64) {
        let Some(keys) = self.keys.as_mut() else {
            return;
        };
        if let Some(state) = keys.get_mut(routing_key) {
            state.last_acked = Some(state.last_acked.map_or(max_offset, |a| a.max(max_offset)));
        }
    }

    /// Drop a key's state. Call when the batcher drops the key, once every
    /// send has resolved and nothing is queued, so there is nothing left to
    /// order against and future offsets are necessarily higher.
    pub fn evict(&mut self, routing_key: &str) {
        if let Some(keys) = self.keys.as_mut() {
            keys.remove(routing_key);
        }
    }
}

impl Drop for SentinelBatch<'_> {
    fn drop(&mut self) {
        if let Some(keys) = &self.keys {
            gauge!("ingestion_consumer_key_sentinel_keys").set(keys.len() as f64);
        }
    }
}

/// The `max_offset` to pass to [`SentinelBatch::note_acked`] for one key's
/// accepted messages, given as `(partition, offset, keyed)` in send order,
/// while `unfinished`, as `(partition, offset)` in send order, go out again.
/// `partition` is the run's first keyed partition, which `note_sent` tracks.
/// `None` when nothing may be ACKed.
pub fn ack_mark(
    partition: i32,
    accepted: impl IntoIterator<Item = (i32, i64, bool)>,
    unfinished: impl IntoIterator<Item = (i32, i64)>,
) -> Option<i64> {
    // A resent message must stay above the mark. A partition revoked and
    // regained inside one poll sends an offset twice, so send order is not
    // offset order and the lowest unfinished offset bounds the mark.
    let resend_from = unfinished
        .into_iter()
        .filter(|&(unfinished_partition, _)| unfinished_partition == partition)
        .map(|(_, offset)| offset)
        .min()
        .unwrap_or(i64::MAX);
    accepted
        .into_iter()
        // An unkeyed message lives on an arbitrary partition under a synthetic
        // key, so it does not advance the mark.
        .filter(|&(message_partition, offset, keyed)| {
            keyed && message_partition == partition && offset < resend_from
        })
        .map(|(_, offset, _)| offset)
        .max()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn msg_at(partition: i32, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "test".into(),
            partition,
            offset,
            timestamp: 0,
            key: Some("t:a".to_string()),
            value: None,
            headers: HashMap::new(),
            generation: 0,
        }
    }

    fn unkeyed_msg_at(partition: i32, offset: i64) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            key: None,
            ..msg_at(partition, offset)
        }
    }

    #[test]
    fn forward_sends_pass() {
        let sentinel = KeyOrderSentinel::new();
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh)
            .is_empty());
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn intra_group_disorder_is_detected() {
        let sentinel = KeyOrderSentinel::new();
        let violations =
            sentinel
                .batch()
                .note_sent("t:a", &[msg_at(0, 2), msg_at(0, 1)], SendKind::Fresh);
        assert_eq!(violations.len(), 1);
        assert_eq!(
            violations[0].kind,
            KeyOrderViolationKind::IntraGroupDisorder
        );
    }

    #[test]
    fn replay_of_unacked_range_is_not_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Resend)
            .is_empty());
    }

    #[test]
    fn fresh_send_below_last_sent_is_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)], SendKind::Fresh);
        let violations =
            sentinel
                .batch()
                .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::SendBelowLastSent);
        // The watermark still advanced: the next in-order send is clean.
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn resend_after_ack_is_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        sentinel.batch().note_acked("t:a", 2);
        // Even the legal retry path must never repeat an ACKed offset.
        let violations = sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 2)], SendKind::Resend);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn a_partial_acks_mark_keeps_the_resend_of_its_unfinished_message_legal() {
        let sentinel = KeyOrderSentinel::new();
        sentinel.batch().note_sent(
            "t:a",
            &[msg_at(0, 1), msg_at(0, 2), msg_at(0, 3)],
            SendKind::Fresh,
        );
        let mark = ack_mark(
            0,
            [(0, 1, true), (0, 3, true), (1, 9, false)],
            [(1, 8), (0, 2)],
        );
        assert_eq!(mark, Some(1));
        sentinel.batch().note_acked("t:a", mark.expect("a mark"));
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 2)], SendKind::Resend)
            .is_empty());
    }

    #[test]
    fn a_redelivered_offset_keeps_the_ack_mark_below_every_unfinished_message() {
        // Offset 1 was sent twice; the worker accepted the first copy only.
        assert_eq!(ack_mark(0, [(0, 1, true)], [(0, 2), (0, 1)]), None);
    }

    #[test]
    fn a_run_whose_tracked_partition_is_wholly_unfinished_acks_nothing() {
        assert_eq!(ack_mark(0, [(1, 100, true)], [(0, 10)]), None);
    }

    #[test]
    fn older_messages_after_acked_newer_ones_are_a_violation() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 4), msg_at(0, 5)], SendKind::Fresh);
        sentinel.batch().note_acked("t:a", 5);
        let violations =
            sentinel
                .batch()
                .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Resend);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn out_of_order_acks_only_advance_the_watermark() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 1), msg_at(0, 2)], SendKind::Fresh);
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 3), msg_at(0, 4)], SendKind::Fresh);
        sentinel.batch().note_acked("t:a", 4);
        sentinel.batch().note_acked("t:a", 2);
        // Forward progress from the true high-water mark is still clean.
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh)
            .is_empty());
        let violations = sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 3)], SendKind::Resend);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].kind, KeyOrderViolationKind::ResendAfterAck);
    }

    #[test]
    fn eviction_drops_state_and_rebaselines() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        sentinel.batch().note_acked("t:a", 5);
        sentinel.batch().evict("t:a");
        assert_eq!(sentinel.key_count(), 0);
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 6)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn clear_resets_all_keys() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        sentinel
            .batch()
            .note_sent("t:b", &[msg_at(1, 7)], SendKind::Fresh);
        sentinel.clear();
        assert_eq!(sentinel.key_count(), 0);
        // Post-rebalance redelivery of uncommitted offsets must not fire.
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 3)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn a_disabled_key_sentinel_checks_nothing_and_holds_no_state() {
        let keys = KeyOrderSentinel::new();
        keys.set_enabled(false);
        keys.batch()
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        assert!(keys
            .batch()
            .note_sent("t:a", &[msg_at(0, 2), msg_at(0, 1)], SendKind::Fresh)
            .is_empty());
        assert_eq!(keys.key_count(), 0, "no state accumulates while disabled");
    }

    #[test]
    fn disabling_key_sentinel_clears_stale_watermarks() {
        let keys = KeyOrderSentinel::new();
        keys.batch()
            .note_sent("t:a", &[msg_at(0, 5)], SendKind::Fresh);
        keys.batch().note_acked("t:a", 5);
        keys.set_enabled(false);
        keys.set_enabled(true);
        assert!(keys
            .batch()
            .note_sent("t:a", &[msg_at(0, 3)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn partition_move_rebaselines() {
        let sentinel = KeyOrderSentinel::new();
        sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 100)], SendKind::Fresh);
        // Same key on a different partition: offsets aren't comparable.
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(3, 1)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn a_send_spanning_two_partitions_keeps_the_first_partitions_watermark() {
        let sentinel = KeyOrderSentinel::new();
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(1, 5), msg_at(0, 100)], SendKind::Fresh)
            .is_empty());
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(1, 6)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn null_key_messages_are_ignored() {
        let sentinel = KeyOrderSentinel::new();
        // Null-key messages have no per-key order, so regressing offsets do not fire.
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[unkeyed_msg_at(1, 5000)], SendKind::Fresh)
            .is_empty());
        assert_eq!(sentinel.key_count(), 0, "unkeyed sends hold no state");
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[unkeyed_msg_at(0, 3)], SendKind::Fresh)
            .is_empty());
    }

    #[test]
    fn null_key_offsets_do_not_inflate_watermarks() {
        // An unkeyed offset must not raise the key's watermarks.
        let sentinel = KeyOrderSentinel::new();
        assert!(sentinel
            .batch()
            .note_sent(
                "t:a",
                &[msg_at(0, 100), unkeyed_msg_at(1, 5000)],
                SendKind::Fresh
            )
            .is_empty());
        sentinel.batch().note_acked("t:a", 100);
        assert!(sentinel
            .batch()
            .note_sent("t:a", &[msg_at(0, 101)], SendKind::Fresh)
            .is_empty());
    }
}
