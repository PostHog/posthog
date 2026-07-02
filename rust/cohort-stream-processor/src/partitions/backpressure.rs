//! The events consume loop's per-partition backpressure state: the holdover of un-dispatched events
//! per partition, kept broker-free so its transitions are unit-testable in isolation.
//!
//! A partition holds a non-empty entry in [`pending`](Backpressure::pending) **iff** its events could
//! not be dispatched, so [`held_partitions`](Backpressure::held_partitions) (`pending.keys()`) is
//! exactly the set to keep paused. Applying that target to the consumer — and re-asserting it so a
//! swallowed pause error or a rebalance that reset librdkafka's pause flags self-heals — is owned by
//! the pauser task (`run_pauser_loop`), not this struct.

use std::collections::{HashMap, HashSet};

use crate::partitions::shuffle_message::ShuffleMessage;

/// Held events per held partition for the events consume loop. Never keeps an empty holdover, so
/// `pending.keys()` is exactly the paused target.
#[derive(Debug, Default)]
pub struct Backpressure {
    /// Un-dispatched events per held partition, coalesced in offset order.
    pending: HashMap<i32, Vec<ShuffleMessage>>,
}

impl Backpressure {
    pub fn new() -> Self {
        Self::default()
    }

    /// Drop the holdover for partitions no longer owned. Their offsets replay on the next owner, and
    /// the pauser task resumes them once they leave the held target.
    pub fn prune_revoked(&mut self, owned: &HashSet<i32>) {
        self.pending
            .retain(|partition, _| owned.contains(partition));
    }

    /// Take the whole holdover for a retry-flush, emptying `pending`; the caller re-[`absorb`](Self::absorb)s
    /// whatever stays full.
    pub fn take_held(&mut self) -> Vec<(i32, Vec<ShuffleMessage>)> {
        std::mem::take(&mut self.pending).into_iter().collect()
    }

    /// Partitions with an outstanding holdover — the paused target, and the set a fresh dispatch must
    /// queue new events behind (never leapfrog) rather than sending them.
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

    /// Partitions currently held (== the paused target size). Feeds the `partitions_paused` gauge.
    pub fn held_partition_count(&self) -> usize {
        self.pending.len()
    }

    /// Total events held across all held partitions. Feeds the `pending_held_events` gauge.
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

    #[test]
    fn a_newly_full_partition_becomes_the_held_target() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)])]));

        assert_eq!(bp.held_partitions(), HashSet::from([5]));
        assert_eq!(bp.held_partition_count(), 1);
    }

    #[test]
    fn a_flushed_partition_leaves_the_held_target() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)])]));

        // Next iteration: the holdover flushed (nothing re-absorbed), so the partition drops out of
        // the held target and the pauser task resumes it.
        let _held = bp.take_held();

        assert!(bp.held_partitions().is_empty());
        assert_eq!(bp.held_partition_count(), 0);
    }

    #[test]
    fn a_still_full_partition_stays_in_the_held_target() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)])]));

        // Retry-flush leaves it full: re-absorbed verbatim, still held.
        let held = bp.take_held();
        bp.absorb(held.into_iter().collect());

        assert_eq!(bp.held_partitions(), HashSet::from([5]));
    }

    #[test]
    fn a_revoked_partition_is_pruned_from_the_held_target() {
        let mut bp = Backpressure::new();
        bp.absorb(HashMap::from([(5, vec![event(10)]), (6, vec![event(20)])]));

        // Only partition 6 is still owned: 5's holdover is dropped for replay on its next owner.
        bp.prune_revoked(&HashSet::from([6]));

        assert_eq!(bp.held_partitions(), HashSet::from([6]));
        assert_eq!(bp.held_partition_count(), 1);
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
