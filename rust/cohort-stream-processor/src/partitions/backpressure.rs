//! The events consume loop's per-partition backpressure state, kept broker-free so its transitions are
//! unit-testable in isolation.
//!
//! Invariant: a partition holds a non-empty entry in [`pending`](Backpressure::pending) **iff** it is
//! paused. [`reconcile`](Backpressure::reconcile) restores it each iteration by diffing the holdover
//! keys against the previously-applied [`paused`](Backpressure::paused) set.

use std::collections::{HashMap, HashSet};

use crate::partitions::shuffle_message::ShuffleMessage;

/// Pause/resume actions the loop must apply to the consumer after a [`reconcile`](Backpressure::reconcile).
#[derive(Debug, Default, PartialEq, Eq)]
pub struct PauseDeltas {
    pub pause: Vec<i32>,
    pub resume: Vec<i32>,
}

/// Held events and paused partitions for the events consume loop. Never keeps an empty holdover, so
/// `pending.keys()` is exactly the set of partitions that should be paused.
#[derive(Debug, Default)]
pub struct Backpressure {
    /// Un-dispatched events per paused partition, coalesced in offset order.
    pending: HashMap<i32, Vec<ShuffleMessage>>,
    /// Partitions currently paused on the consumer — what the last [`reconcile`](Self::reconcile)
    /// applied. Diffed against the holdover key set to compute the next pause/resume deltas.
    paused: HashSet<i32>,
}

impl Backpressure {
    pub fn new() -> Self {
        Self::default()
    }

    /// Drop holdover and pause-tracking for partitions no longer owned. Their offsets replay on the
    /// next owner; resuming a partition we no longer own would only error.
    pub fn prune_revoked(&mut self, owned: &HashSet<i32>) {
        self.pending
            .retain(|partition, _| owned.contains(partition));
        self.paused.retain(|partition| owned.contains(partition));
    }

    /// Take the whole holdover for a retry-flush, emptying `pending`; the caller reinstates whatever
    /// stays full via [`set_pending`](Self::set_pending). Leaves `paused` untouched — the reconcile
    /// resumes anything that flushed.
    pub fn take_held(&mut self) -> Vec<(i32, Vec<ShuffleMessage>)> {
        std::mem::take(&mut self.pending).into_iter().collect()
    }

    /// Reinstate the post-flush holdover (the partitions whose channel is still full).
    pub fn set_pending(&mut self, pending: HashMap<i32, Vec<ShuffleMessage>>) {
        self.pending = pending;
    }

    /// Partitions with an outstanding holdover — the set a fresh dispatch must queue new events behind
    /// (never leapfrog) rather than sending them.
    pub fn held_partitions(&self) -> HashSet<i32> {
        self.pending.keys().copied().collect()
    }

    /// Append un-dispatched events to their partition's holdover in offset order. Empty batches are
    /// skipped, so a present entry always means a non-empty holdover.
    pub fn absorb(&mut self, full: HashMap<i32, Vec<ShuffleMessage>>) {
        for (partition, mut messages) in full {
            if messages.is_empty() {
                continue;
            }
            self.pending
                .entry(partition)
                .or_default()
                .append(&mut messages);
        }
    }

    /// Diff the target paused set (partitions that still hold events) against the currently-paused set,
    /// returning the pause/resume actions and adopting the target as the new paused set.
    pub fn reconcile(&mut self) -> PauseDeltas {
        let target: HashSet<i32> = self.pending.keys().copied().collect();
        let pause = target.difference(&self.paused).copied().collect();
        let resume = self.paused.difference(&target).copied().collect();
        self.paused = target;
        PauseDeltas { pause, resume }
    }

    /// Partitions currently paused (== holdover count). Feeds the `partitions_paused` gauge.
    pub fn paused_count(&self) -> usize {
        self.paused.len()
    }

    /// Total events held across all paused partitions. Feeds the `pending_held_events` gauge.
    pub fn held_event_count(&self) -> usize {
        self.pending.values().map(Vec::len).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::consumers::events::CohortStreamEvent;

    fn event(cse_offset: i64) -> ShuffleMessage {
        ShuffleMessage::Event {
            event: Box::new(CohortStreamEvent {
                team_id: 1,
                person_id: "p".to_string(),
                distinct_id: "d".to_string(),
                uuid: "u".to_string(),
                event: "$pageview".to_string(),
                timestamp: "2026-05-26 12:34:56.789000".to_string(),
                properties: None,
                person_properties: None,
                elements_chain: None,
                source_offset: cse_offset,
                source_partition: 0,
                redirected_from: None,
                redirect_hops: 0,
            }),
            cse_offset,
        }
    }

    fn offsets(messages: &[ShuffleMessage]) -> Vec<i64> {
        messages
            .iter()
            .filter_map(ShuffleMessage::event_offset)
            .collect()
    }

    fn set(partitions: [i32; 1]) -> HashSet<i32> {
        partitions.into_iter().collect()
    }

    #[test]
    fn a_newly_full_partition_is_stashed_and_paused() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)])]));

        let deltas = bp.reconcile();
        assert_eq!(deltas.pause, vec![5]);
        assert!(deltas.resume.is_empty());
        assert!(bp.held_partitions().contains(&5));
        assert_eq!(bp.paused_count(), 1);
    }

    #[test]
    fn a_fully_flushed_partition_is_resumed_and_cleared() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)])]));
        assert_eq!(bp.reconcile().pause, vec![5]);

        // Next iteration: the holdover flushed (nothing stays full).
        let _held = bp.take_held();
        bp.set_pending(HashMap::new());
        let deltas = bp.reconcile();

        assert!(deltas.pause.is_empty());
        assert_eq!(deltas.resume, vec![5]);
        assert!(bp.held_partitions().is_empty());
        assert_eq!(bp.paused_count(), 0);
    }

    #[test]
    fn a_still_full_partition_stays_paused_with_no_delta() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)])]));
        assert_eq!(bp.reconcile().pause, vec![5]);

        // Retry-flush leaves it full: reinstated verbatim, no pause/resume churn.
        let held = bp.take_held();
        bp.set_pending(held.into_iter().collect());
        let deltas = bp.reconcile();

        assert!(deltas.pause.is_empty() && deltas.resume.is_empty());
        assert!(bp.held_partitions().contains(&5));
    }

    #[test]
    fn a_revoked_paused_partition_is_pruned_and_never_resumed() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)])]));
        assert_eq!(bp.reconcile().pause, vec![5]);

        // Partition 5 revoked: dropped, not resumed.
        bp.prune_revoked(&set([9]));
        let deltas = bp.reconcile();

        assert!(deltas.pause.is_empty());
        assert!(
            deltas.resume.is_empty(),
            "a revoked partition is not resumed"
        );
        assert!(bp.held_partitions().is_empty());
        assert_eq!(bp.paused_count(), 0);
    }

    #[test]
    fn absorb_coalesces_fresh_events_after_the_existing_holdover_in_offset_order() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10), event(11)])]));
        // A straggler that arrived after the pause queues behind the older held offsets.
        bp.absorb(HashMap::from([(5, vec![event(12)])]));

        let held: HashMap<i32, Vec<ShuffleMessage>> = bp.take_held().into_iter().collect();
        assert_eq!(offsets(&held[&5]), vec![10, 11, 12]);
    }

    #[test]
    fn held_event_count_sums_across_partitions() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([
            (5, vec![event(10), event(11)]),
            (6, vec![event(20)]),
        ]));
        assert_eq!(bp.held_event_count(), 3);
    }
}
