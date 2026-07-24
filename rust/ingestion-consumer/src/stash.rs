//! Deferred-message stash for graceful drain / worker loss.
//!
//! When a routing key is pinned to a worker that is draining or dead, new
//! messages for that key can't be sent there (it must finish and exit) and
//! can't be re-routed elsewhere yet (the key's earlier messages are still in
//! flight on that worker — re-routing now would reorder the distinct_id). So
//! they are *stashed* here until the worker's in-flight resolves, then flushed
//! (re-routed) in order.
//!
//! Entries are held in a per-routing-key FIFO ordered by **batch sequence** —
//! the arrival order of the batch that produced them, assigned via
//! [`Stash::register_batch`] on the consumer loop before any deferral for the
//! batch can occur. Batch ids themselves (timestamp + random) are not
//! sortable, and deferrals can arrive out of batch order (`defer_failed` lands
//! in send-gather order), so insertion order can't be trusted; the sequence
//! can.
//!
//! Besides the queues, the stash keeps:
//! - a per-batch live-entry count, so the consumer can flush a batch's
//!   deferred work as part of completing that batch (preserving per-batch
//!   offset ownership and oldest-first order);
//! - a per-routing-key **outstanding count**, which the dispatcher consults to
//!   (a) keep deferring new messages for a key that already has deferred work,
//!   so they can't race ahead, and (b) avoid evicting a pin while its key still
//!   has deferred work pending.
//!
//! A group contributes 1 to its key's outstanding count from [`Stash::defer`]
//! until [`Stash::completed`] (i.e. until it has actually been routed). Pulling
//! groups out to attempt a flush ([`Stash::take_batch`]) and putting back the
//! ones that couldn't route ([`Stash::put_back`]) do not change the count.

use std::collections::{HashMap, VecDeque};

use crate::types::SerializedKafkaMessage;

/// Messages for one routing key, deferred because the key's pinned worker is
/// draining or dead.
pub struct DeferredGroup {
    pub routing_key: String,
    pub messages: Vec<SerializedKafkaMessage>,
}

impl DeferredGroup {
    pub fn message_count(&self) -> usize {
        self.messages.len()
    }
}

struct Entry {
    batch_seq: u64,
    batch_id: String,
    messages: Vec<SerializedKafkaMessage>,
}

#[derive(Default)]
pub struct Stash {
    /// Per routing key: deferred entries ordered by batch sequence (oldest first).
    queues: HashMap<String, VecDeque<Entry>>,
    /// Batch id → arrival sequence, assigned by `register_batch` (or lazily on
    /// first deferral for callers that don't register, e.g. tests).
    batch_seqs: HashMap<String, u64>,
    next_seq: u64,
    /// Batch id → number of entries currently stashed for it.
    batch_live: HashMap<String, usize>,
    /// Per routing key: how many deferred groups are outstanding (not yet routed).
    outstanding: HashMap<String, u32>,
}

impl Stash {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record `batch_id`'s arrival order. Must be called in true batch order
    /// (i.e. from the consumer loop, before the batch is processed) — the
    /// sequence orders a key's entries across batches, so a later deferral for
    /// an older batch still queues ahead of a newer batch's entries.
    pub fn register_batch(&mut self, batch_id: &str) {
        if !self.batch_seqs.contains_key(batch_id) {
            self.batch_seqs.insert(batch_id.to_string(), self.next_seq);
            self.next_seq += 1;
        }
    }

    /// Forget a completed batch's sequence. Call once the batch is fully done
    /// (committed) — no further deferral for it can occur after that.
    pub fn release_batch(&mut self, batch_id: &str) {
        self.batch_seqs.remove(batch_id);
    }

    fn seq_for(&mut self, batch_id: &str) -> u64 {
        if let Some(&seq) = self.batch_seqs.get(batch_id) {
            return seq;
        }
        let seq = self.next_seq;
        self.next_seq += 1;
        self.batch_seqs.insert(batch_id.to_string(), seq);
        seq
    }

    fn insert_entry(&mut self, routing_key: &str, entry: Entry) {
        *self.batch_live.entry(entry.batch_id.clone()).or_insert(0) += 1;
        let queue = self.queues.entry(routing_key.to_string()).or_default();
        // Ordered by batch_seq, stable for equal seqs; append is the common case.
        let pos = queue
            .iter()
            .rposition(|e| e.batch_seq <= entry.batch_seq)
            .map_or(0, |i| i + 1);
        queue.insert(pos, entry);
    }

    /// Defer a group produced by `batch_id`, bumping its key's outstanding count.
    pub fn defer(&mut self, batch_id: &str, group: DeferredGroup) {
        let batch_seq = self.seq_for(batch_id);
        *self
            .outstanding
            .entry(group.routing_key.clone())
            .or_insert(0) += 1;
        self.insert_entry(
            &group.routing_key,
            Entry {
                batch_seq,
                batch_id: batch_id.to_string(),
                messages: group.messages,
            },
        );
    }

    /// Whether the key currently has any outstanding deferred groups. New
    /// messages for such a key must keep deferring, and its pin must not be
    /// evicted.
    pub fn is_deferring(&self, routing_key: &str) -> bool {
        self.outstanding.get(routing_key).is_some_and(|&n| n > 0)
    }

    /// Whether `batch_id` has any deferred groups still awaiting flush.
    pub fn has_batch(&self, batch_id: &str) -> bool {
        self.batch_live.get(batch_id).is_some_and(|&n| n > 0)
    }

    /// Remove and return a batch's deferred groups so the caller can try to
    /// route them. Routed groups must be acknowledged with [`Stash::completed`];
    /// groups that couldn't route are returned via [`Stash::put_back`]. Neither
    /// this call nor `put_back` changes outstanding counts — only `completed` does.
    pub fn take_batch(&mut self, batch_id: &str) -> Vec<DeferredGroup> {
        let mut taken = Vec::new();
        self.queues.retain(|routing_key, queue| {
            let mut i = 0;
            while i < queue.len() {
                if queue[i].batch_id == batch_id {
                    let entry = queue.remove(i).expect("index in bounds");
                    taken.push(DeferredGroup {
                        routing_key: routing_key.clone(),
                        messages: entry.messages,
                    });
                } else {
                    i += 1;
                }
            }
            !queue.is_empty()
        });
        self.batch_live.remove(batch_id);
        taken
    }

    /// Pop the key's oldest deferred entry for eager release, returning the
    /// owning batch id and the messages. Does not change the outstanding
    /// count — the caller is routing the group now, and [`Stash::completed`]
    /// fires when its send resolves, exactly as with [`Stash::take_batch`].
    pub fn pop_next(&mut self, routing_key: &str) -> Option<(String, Vec<SerializedKafkaMessage>)> {
        let queue = self.queues.get_mut(routing_key)?;
        let entry = queue.pop_front()?;
        if queue.is_empty() {
            self.queues.remove(routing_key);
        }
        match self.batch_live.get_mut(&entry.batch_id) {
            Some(n) if *n > 1 => *n -= 1,
            _ => {
                self.batch_live.remove(&entry.batch_id);
            }
        }
        Some((entry.batch_id, entry.messages))
    }

    /// Re-stash a taken group that couldn't be routed yet (no healthy worker).
    pub fn put_back(&mut self, batch_id: &str, group: DeferredGroup) {
        let batch_seq = self.seq_for(batch_id);
        self.insert_entry(
            &group.routing_key,
            Entry {
                batch_seq,
                batch_id: batch_id.to_string(),
                messages: group.messages,
            },
        );
    }

    /// Mark one deferred group for `routing_key` as routed — decrements the
    /// key's outstanding count.
    pub fn completed(&mut self, routing_key: &str) {
        if let Some(n) = self.outstanding.get_mut(routing_key) {
            *n -= 1;
            if *n == 0 {
                self.outstanding.remove(routing_key);
            }
        }
    }

    /// Total deferred groups currently stashed (for metrics/tests).
    pub fn len(&self) -> usize {
        self.queues.values().map(VecDeque::len).sum()
    }

    pub fn is_empty(&self) -> bool {
        self.queues.is_empty()
    }

    /// Number of batches that currently have deferred groups awaiting flush.
    pub fn batch_count(&self) -> usize {
        self.batch_live.len()
    }

    /// Total deferred messages currently stashed across all batches and groups.
    pub fn message_count(&self) -> usize {
        self.queues
            .values()
            .flat_map(|queue| queue.iter())
            .map(|entry| entry.messages.len())
            .sum()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;
    use crate::types::SerializedKafkaMessage;

    fn msg(distinct_id: &str) -> SerializedKafkaMessage {
        let mut headers = HashMap::new();
        headers.insert("token".to_string(), "t".to_string());
        headers.insert("distinct_id".to_string(), distinct_id.to_string());
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: None,
            value: None,
            headers,
        }
    }

    fn group(key: &str, n: usize) -> DeferredGroup {
        DeferredGroup {
            routing_key: key.to_string(),
            messages: (0..n).map(|_| msg(key)).collect(),
        }
    }

    #[test]
    fn test_defer_marks_key_deferring() {
        let mut stash = Stash::new();
        assert!(!stash.is_deferring("t:a"));

        stash.defer("batch-1", group("t:a", 2));
        assert!(stash.is_deferring("t:a"));
        assert!(stash.has_batch("batch-1"));
        assert_eq!(stash.len(), 1);
    }

    #[test]
    fn test_completed_clears_deferring_only_when_count_hits_zero() {
        let mut stash = Stash::new();
        // Same key deferred by two batches → outstanding count 2.
        stash.defer("batch-1", group("t:a", 1));
        stash.defer("batch-2", group("t:a", 1));
        assert!(stash.is_deferring("t:a"));

        stash.completed("t:a");
        assert!(
            stash.is_deferring("t:a"),
            "still deferring with one outstanding"
        );

        stash.completed("t:a");
        assert!(
            !stash.is_deferring("t:a"),
            "no longer deferring once all routed"
        );
    }

    #[test]
    fn test_take_batch_removes_groups_without_changing_outstanding() {
        let mut stash = Stash::new();
        stash.defer("batch-1", group("t:a", 1));

        let taken = stash.take_batch("batch-1");
        assert_eq!(taken.len(), 1);
        assert!(!stash.has_batch("batch-1"), "batch's groups are removed");
        assert!(
            stash.is_deferring("t:a"),
            "taking to attempt a flush must not clear the outstanding count"
        );
    }

    #[test]
    fn test_put_back_re_stashes_without_double_counting() {
        let mut stash = Stash::new();
        stash.defer("batch-1", group("t:a", 1));
        let mut taken = stash.take_batch("batch-1");

        // Couldn't route — put it back.
        stash.put_back("batch-1", taken.pop().unwrap());
        assert!(stash.has_batch("batch-1"));
        assert!(stash.is_deferring("t:a"));

        // Now it routes: take + completed → count clears.
        let mut taken = stash.take_batch("batch-1");
        stash.completed(&taken.pop().unwrap().routing_key);
        assert!(!stash.is_deferring("t:a"));
    }

    #[test]
    fn test_completed_beyond_outstanding_is_noop() {
        // A spurious extra completion (e.g. a double resolve for the same key)
        // must be a no-op — not an underflow that would leave the key
        // "deferring" forever and stall it permanently.
        let mut stash = Stash::new();
        stash.defer("batch-1", group("t:a", 1));

        stash.completed("t:a");
        assert!(!stash.is_deferring("t:a"));

        stash.completed("t:a");
        assert!(!stash.is_deferring("t:a"));
    }

    #[test]
    fn test_take_unknown_batch_is_empty() {
        let mut stash = Stash::new();
        assert!(stash.take_batch("nope").is_empty());
    }

    #[test]
    fn test_depth_counts_batches_groups_and_messages() {
        let mut stash = Stash::new();
        stash.defer("batch-1", group("t:a", 2));
        stash.defer("batch-1", group("t:b", 1));
        stash.defer("batch-2", group("t:a", 3));

        assert_eq!(stash.batch_count(), 2);
        assert_eq!(stash.len(), 3, "three groups across two batches");
        assert_eq!(stash.message_count(), 6, "2 + 1 + 3 messages");

        // Taking a batch out to attempt a flush drops it from the depth counts.
        let _ = stash.take_batch("batch-1");
        assert_eq!(stash.batch_count(), 1);
        assert_eq!(stash.message_count(), 3);
    }

    #[test]
    fn test_late_deferral_for_registered_older_batch_queues_ahead() {
        // batch-1 arrives before batch-2 (registration order), but its
        // deferral lands later (a failed send re-defers after the newer batch
        // already stashed). The older batch's entry must still queue ahead of
        // the newer batch's for the same key.
        let mut stash = Stash::new();
        stash.register_batch("batch-1");
        stash.register_batch("batch-2");

        stash.defer("batch-2", group("t:a", 1));
        stash.defer("batch-1", group("t:a", 2));

        let (batch_id, messages) = stash.pop_next("t:a").unwrap();
        assert_eq!(batch_id, "batch-1", "older batch pops first");
        assert_eq!(messages.len(), 2);
        let (batch_id, _) = stash.pop_next("t:a").unwrap();
        assert_eq!(batch_id, "batch-2");
        assert!(stash.pop_next("t:a").is_none());
    }

    #[test]
    fn test_pop_next_keeps_outstanding_until_completed() {
        let mut stash = Stash::new();
        stash.defer("batch-1", group("t:a", 1));

        let (batch_id, _) = stash.pop_next("t:a").unwrap();
        assert_eq!(batch_id, "batch-1");
        assert!(
            !stash.has_batch("batch-1"),
            "popped entry no longer counts toward its batch"
        );
        assert!(
            stash.is_deferring("t:a"),
            "popping for a flush attempt must not clear the outstanding count"
        );

        stash.completed("t:a");
        assert!(!stash.is_deferring("t:a"));
    }
}
