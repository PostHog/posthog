//! Per-key ordered deferral, extracted from the shape proven in
//! `ingestion-consumer`'s stash and adopted by the personhog router's.
//!
//! Both services face the same problem one layer apart: work is pinned to
//! a key-sticky target (a worker, an owner pod) that is temporarily
//! unroutable, and per-key ordering must survive the outage — including
//! across *failed delivery attempts*. The queue makes that survivable by
//! construction rather than by choreography:
//!
//! - Every entry is stamped with a monotonic sequence at admission, so an
//!   entry's position is a property of the entry, not of queue physics. A
//!   failed attempt cannot corrupt order because putting an entry back
//!   restores it to its sequence position.
//! - Entries leave only through [`KeyedStash::complete`] — a
//!   definitive outcome. An attempt that cannot finish puts its entries
//!   back and they will be re-attempted first, in order.
//! - [`KeyedStash::is_deferring`] is the outstanding gate: while a
//!   key has queued or in-attempt entries, new work for that key must be
//!   deferred behind them — never sent directly — or it would race ahead
//!   of the backlog.
//!
//! Deliberately single-owner (`&mut self`) and free of I/O, locking, and
//! policy: callers wrap it in their own concurrency envelope and layer
//! their own admission bounds, batch accounting, or reply plumbing on
//! top, exactly as the two existing stashes do.

use std::collections::{HashMap, VecDeque};
use std::hash::Hash;

/// One deferred entry: the caller's item plus the admission-order stamp
/// that fixes its position among its key's entries forever.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry<T> {
    pub seq: u64,
    pub item: T,
}

/// A per-key ordered deferral queue. See the crate docs for the contract.
#[derive(Debug)]
pub struct KeyedStash<K, T> {
    queues: HashMap<K, VecDeque<Entry<T>>>,
    /// Per key: entries taken for an attempt and not yet completed or put
    /// back. Counted so `is_deferring` covers in-flight work, not just
    /// queued work.
    in_attempt: HashMap<K, usize>,
    next_seq: u64,
    len: usize,
}

impl<K, T> Default for KeyedStash<K, T> {
    fn default() -> Self {
        Self {
            queues: HashMap::new(),
            in_attempt: HashMap::new(),
            next_seq: 0,
            len: 0,
        }
    }
}

impl<K: Eq + Hash + Clone, T> KeyedStash<K, T> {
    pub fn new() -> Self {
        Self::default()
    }

    /// Defer `item` behind everything already deferred for `key`.
    /// Returns the entry's sequence stamp.
    pub fn push(&mut self, key: K, item: T) -> u64 {
        let seq = self.next_seq;
        self.next_seq += 1;
        self.queues
            .entry(key)
            .or_default()
            .push_back(Entry { seq, item });
        self.len += 1;
        seq
    }

    /// Whether new work for `key` must be deferred: the key has queued
    /// entries, or entries taken for an attempt whose outcome is not yet
    /// known. Sending new work directly while this holds would let it
    /// race ahead of the key's backlog.
    pub fn is_deferring(&self, key: &K) -> bool {
        self.in_attempt.get(key).is_some_and(|n| *n > 0)
            || self.queues.get(key).is_some_and(|q| !q.is_empty())
    }

    /// Take up to `max` entries from the front of `key`'s queue for a
    /// delivery attempt. The entries count as in-attempt until each is
    /// either [`complete`](Self::complete)d or returned via
    /// [`put_back`](Self::put_back); dropping them instead loses items
    /// and permanently latches `is_deferring` for the key.
    pub fn take_front(&mut self, key: &K, max: usize) -> Vec<Entry<T>> {
        let Some(queue) = self.queues.get_mut(key) else {
            return Vec::new();
        };
        let n = max.min(queue.len());
        let taken: Vec<Entry<T>> = queue.drain(..n).collect();
        if queue.is_empty() {
            self.queues.remove(key);
        }
        if !taken.is_empty() {
            *self.in_attempt.entry(key.clone()).or_default() += taken.len();
            self.len -= taken.len();
        }
        taken
    }

    /// Record a definitive outcome for one in-attempt entry of `key` —
    /// delivered, or failed in a way that was reported to its origin.
    /// The entry is gone; its successors may now be attempted.
    pub fn complete(&mut self, key: &K) {
        let count = self
            .in_attempt
            .get_mut(key)
            .expect("complete() without a matching take_front()");
        *count -= 1;
        if *count == 0 {
            self.in_attempt.remove(key);
        }
    }

    /// Return entries whose attempt was aborted before any outcome
    /// existed (supersession, a target that became unroutable). They
    /// re-enter at their sequence positions — ahead of everything
    /// admitted after them — so the next attempt sees them first, in
    /// order.
    pub fn put_back(&mut self, key: &K, entries: Vec<Entry<T>>) {
        if entries.is_empty() {
            return;
        }
        let count = self
            .in_attempt
            .get_mut(key)
            .expect("put_back() without a matching take_front()");
        *count -= entries.len();
        if *count == 0 {
            self.in_attempt.remove(key);
        }
        self.len += entries.len();
        let queue = self.queues.entry(key.clone()).or_default();
        // Taken entries always predate everything still queued, so they
        // belong at the front; restoring in reverse preserves their
        // internal order. The debug assertion pins the seq invariant the
        // fast path relies on.
        debug_assert!(
            queue
                .front()
                .is_none_or(|next| entries.last().is_none_or(|e| e.seq < next.seq)),
            "put_back entries must predate every queued entry"
        );
        for entry in entries.into_iter().rev() {
            queue.push_front(entry);
        }
    }

    /// Keys that currently have queued entries, in no particular order.
    /// In-attempt-only keys are excluded: their next attempt is decided
    /// by the outcome of the current one.
    pub fn keys_with_backlog(&self) -> impl Iterator<Item = &K> {
        self.queues.keys()
    }

    /// Total queued entries across all keys (in-attempt entries are not
    /// queued).
    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0 && self.in_attempt.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    /// The outstanding gate covers both queued and in-attempt work: a key
    /// stays "deferring" from first push until the last outcome, never
    /// dropping out in between — the window where new work could race
    /// ahead of a retry.
    #[test]
    fn the_gate_holds_across_the_attempt_window() {
        let mut q: KeyedStash<u8, u32> = KeyedStash::new();
        assert!(!q.is_deferring(&1));

        q.push(1, 10);
        assert!(q.is_deferring(&1));

        let taken = q.take_front(&1, 8);
        assert_eq!(taken.len(), 1);
        assert!(q.is_deferring(&1), "in-attempt work must keep the gate up");

        q.put_back(&1, taken);
        assert!(q.is_deferring(&1));

        let taken = q.take_front(&1, 8);
        q.complete(&1);
        assert!(!q.is_deferring(&1));
        drop(taken);
    }

    /// Put-back restores aborted entries ahead of work admitted after
    /// them — the leapfrog case: a retry must never be overtaken by a
    /// newer same-key item.
    #[test]
    fn put_back_precedes_later_admissions() {
        let mut q: KeyedStash<u8, &str> = KeyedStash::new();
        q.push(1, "a");
        q.push(1, "b");
        let taken = q.take_front(&1, 2);
        q.push(1, "c");
        q.put_back(&1, taken);

        let order: Vec<&str> = q.take_front(&1, 8).into_iter().map(|e| e.item).collect();
        assert_eq!(order, vec!["a", "b", "c"]);
    }

    /// Model-based property check: against an arbitrary interleaving of
    /// push / take / complete / put_back across several keys, delivery
    /// order per key equals admission order per key (completions observe
    /// strictly increasing seqs), and every admitted item is exactly once
    /// delivered or still held. This is the invariant that makes internal
    /// retry safe to build on top.
    #[derive(Debug, Clone)]
    enum Op {
        Push { key: u8 },
        AttemptDeliver { key: u8, max: u8 },
        AttemptAbort { key: u8, max: u8 },
    }

    fn op_strategy() -> impl Strategy<Value = Op> {
        prop_oneof![
            (0u8..4).prop_map(|key| Op::Push { key }),
            (0u8..4, 1u8..5).prop_map(|(key, max)| Op::AttemptDeliver { key, max }),
            (0u8..4, 1u8..5).prop_map(|(key, max)| Op::AttemptAbort { key, max }),
        ]
    }

    proptest! {
        #[test]
        fn per_key_order_and_conservation_hold(ops in proptest::collection::vec(op_strategy(), 1..120)) {
            let mut q: KeyedStash<u8, u64> = KeyedStash::new();
            let mut admitted: HashMap<u8, u64> = HashMap::new();
            let mut delivered: HashMap<u8, Vec<u64>> = HashMap::new();
            let mut admitted_total = 0u64;

            for op in ops {
                match op {
                    Op::Push { key } => {
                        let n = admitted.entry(key).or_default();
                        q.push(key, *n);
                        *n += 1;
                        admitted_total += 1;
                    }
                    Op::AttemptDeliver { key, max } => {
                        let taken = q.take_front(&key, max as usize);
                        let mut last_seq = None;
                        for entry in taken {
                            prop_assert!(last_seq.is_none_or(|s| s < entry.seq));
                            last_seq = Some(entry.seq);
                            delivered.entry(key).or_default().push(entry.item);
                            q.complete(&key);
                        }
                    }
                    Op::AttemptAbort { key, max } => {
                        let taken = q.take_front(&key, max as usize);
                        q.put_back(&key, taken);
                    }
                }
            }

            // Per-key delivery order == admission order.
            for (key, items) in &delivered {
                let expected: Vec<u64> = (0..items.len() as u64).collect();
                prop_assert_eq!(items, &expected, "key {} delivered out of order", key);
            }
            // Conservation: everything admitted is delivered or still queued.
            let delivered_total: usize = delivered.values().map(Vec::len).sum();
            prop_assert_eq!(delivered_total + q.len(), admitted_total as usize);
        }
    }
}
