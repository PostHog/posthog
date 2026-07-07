//! Deferred-message stash for graceful drain / worker loss.
//!
//! When a routing key is pinned to a worker that is draining or dead, new
//! messages for that key can't be sent there (it must finish and exit) and
//! can't be re-routed elsewhere yet (the key's earlier messages are still in
//! flight on that worker — re-routing now would reorder the distinct_id). So
//! they are *stashed* here until the worker's in-flight resolves, then flushed
//! (re-routed) in order.
//!
//! The stash keeps two things:
//! - the deferred groups themselves, keyed by the batch that produced them, so
//!   the consumer can flush a batch's deferred work as part of completing that
//!   batch (preserving per-batch offset ownership and oldest-first order);
//! - a per-routing-key **outstanding count**, which the dispatcher consults to
//!   (a) keep deferring new messages for a key that already has deferred work,
//!   so they can't race ahead, and (b) avoid evicting a pin while its key still
//!   has deferred work pending.
//!
//! A group contributes 1 to its key's outstanding count from [`Stash::defer`]
//! until [`Stash::completed`] (i.e. until it has actually been routed). Pulling
//! groups out to attempt a flush ([`Stash::take_batch`]) and putting back the
//! ones that couldn't route ([`Stash::put_back`]) do not change the count.

use std::collections::HashMap;

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

#[derive(Default)]
pub struct Stash {
    /// Deferred groups awaiting flush, keyed by the batch id that produced them.
    by_batch: HashMap<String, Vec<DeferredGroup>>,
    /// Per routing key: how many deferred groups are outstanding (not yet routed).
    outstanding: HashMap<String, u32>,
}

impl Stash {
    pub fn new() -> Self {
        Self::default()
    }

    /// Defer a group produced by `batch_id`, bumping its key's outstanding count.
    pub fn defer(&mut self, batch_id: &str, group: DeferredGroup) {
        *self
            .outstanding
            .entry(group.routing_key.clone())
            .or_insert(0) += 1;
        self.by_batch
            .entry(batch_id.to_string())
            .or_default()
            .push(group);
    }

    /// Whether the key currently has any outstanding deferred groups. New
    /// messages for such a key must keep deferring, and its pin must not be
    /// evicted.
    pub fn is_deferring(&self, routing_key: &str) -> bool {
        self.outstanding.get(routing_key).is_some_and(|&n| n > 0)
    }

    /// Whether `batch_id` has any deferred groups still awaiting flush.
    pub fn has_batch(&self, batch_id: &str) -> bool {
        self.by_batch.contains_key(batch_id)
    }

    /// Remove and return a batch's deferred groups so the caller can try to
    /// route them. Routed groups must be acknowledged with [`Stash::completed`];
    /// groups that couldn't route are returned via [`Stash::put_back`]. Neither
    /// this call nor `put_back` changes outstanding counts — only `completed` does.
    pub fn take_batch(&mut self, batch_id: &str) -> Vec<DeferredGroup> {
        self.by_batch.remove(batch_id).unwrap_or_default()
    }

    /// Re-stash a taken group that couldn't be routed yet (no healthy worker).
    pub fn put_back(&mut self, batch_id: &str, group: DeferredGroup) {
        self.by_batch
            .entry(batch_id.to_string())
            .or_default()
            .push(group);
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
        self.by_batch.values().map(Vec::len).sum()
    }

    pub fn is_empty(&self) -> bool {
        self.by_batch.is_empty()
    }

    /// Number of batches that currently have deferred groups awaiting flush.
    pub fn batch_count(&self) -> usize {
        self.by_batch.len()
    }

    /// Total deferred messages currently stashed across all batches and groups.
    pub fn message_count(&self) -> usize {
        self.by_batch
            .values()
            .flat_map(|groups| groups.iter())
            .map(DeferredGroup::message_count)
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
}
