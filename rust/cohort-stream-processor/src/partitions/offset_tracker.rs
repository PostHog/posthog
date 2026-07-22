//! [`OffsetTracker`] — per-partition commit tracking: the next offset to consume after a partition's
//! batch is durably processed ([`OffsetTracker::committable_offsets`]) and the offset Kafka last
//! acked (the recovery point on restart). No batch-ID ordering checks: the single per-partition
//! channel plus serial worker already guarantee in-partition order.
//!
//! Per-key replay dedup is a separate concern, owned by
//! [`AppliedOffsets`](crate::stage1::state::AppliedOffsets) on each `cf_behavioral` record.

use std::collections::{BTreeSet, HashMap};
use std::sync::Arc;

use dashmap::DashMap;

/// Per-partition consume/commit progress.
#[derive(Debug, Default)]
struct PartitionProgress {
    /// Identity for one partition tenure. A deferred token from a forgotten tenure must not release
    /// an equal offset deferred by a later owner.
    tenure: Arc<()>,
    /// Next offset to consume (highest processed `+ 1`), the value committed to Kafka. Monotonic.
    /// `0` is the "never processed" sentinel; a real mark is always `≥ 1`, so
    /// [`committable_offsets`](OffsetTracker::committable_offsets) treats `0` as nothing to commit.
    processed_offset: i64,
    /// Dispatch ceiling: highest next-offset actually routed to a worker.
    /// [`mark_processed`](OffsetTracker::mark_processed) clamps `processed_offset` to this so a
    /// consumed-but-never-dispatched offset (dropped buffer, route error) can't be committed past.
    /// In correct operation it equals the max routed offset `+ 1`, so the clamp only bites on a bug.
    dispatched_offset: i64,
    /// Commit floor pinned by [`hold`](OffsetTracker::hold): the lowest next-offset a handler asked to
    /// *redeliver* because a failed step left no other recovery (a store write that was the last copy
    /// of merge/transfer state, a forward produce with no local outbox). `None` = no hold.
    ///
    /// [`committable_offsets`](OffsetTracker::committable_offsets) caps its result at this, so a later
    /// success on the same partition — which advances `processed_offset` past the failed message —
    /// cannot leapfrog the held offset and silently skip it. A hold only ever *lowers* the floor
    /// ([`min`]); it is **sticky** for the worker's tenure (no within-tenure clear — a single failed
    /// message is never reprocessed before redelivery), cleared only by
    /// [`forget_partition`](OffsetTracker::forget_partition) and the next tenure's replay. That makes a
    /// persistent store error a *visible* commit-stall (lag grows; emit the `held_offset` gauge and
    /// alert) rather than a silent state loss — the intended fail-stop for a correctness-critical pipeline.
    held_offset: Option<i64>,
    /// Releasable commit floors owned by in-flight work that outlives its consumed message. Unlike
    /// [`held_offset`](Self::held_offset), each floor is removed explicitly when that work finishes.
    deferred: BTreeSet<i64>,
    /// Last offset Kafka acked as committed. The gap to `processed_offset` is the window Kafka
    /// replays after a crash.
    committed_offset: i64,
}

impl PartitionProgress {
    fn mark_processed(&mut self, next_offset: i64) -> MarkOutcome {
        let capped = next_offset.min(self.dispatched_offset);
        self.processed_offset = self.processed_offset.max(capped);
        if capped < next_offset {
            MarkOutcome::CappedAheadOfDispatch
        } else {
            MarkOutcome::WithinDispatch
        }
    }

    fn committable_offset(&self) -> Option<i64> {
        let committable = [
            Some(self.processed_offset),
            self.held_offset,
            self.deferred.first().copied(),
        ]
        .into_iter()
        .flatten()
        .min()
        .expect("processed offset always supplies a commit candidate");

        (self.processed_offset > 0 && committable > 0).then_some(committable)
    }
}

/// Ownership token for a releasable commit floor created by [`OffsetTracker::defer`].
///
/// The token is deliberately non-`Clone`: one in-flight operation owns one completion. Dropping it
/// leaves the floor pinned until the partition is forgotten, so a lost job fails closed and Kafka
/// replays the message on the next tenure.
#[derive(Debug)]
#[must_use = "a deferred offset must be completed after its durable work finishes"]
pub struct DeferredOffset {
    partition: i32,
    offset: i64,
    tenure: Arc<()>,
}

impl DeferredOffset {
    pub(crate) fn offset(&self) -> i64 {
        self.offset
    }
}

/// What [`OffsetTracker::mark_processed`] did with a mark — returned so the worker can emit a metric
/// without the tracker importing `metrics`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MarkOutcome {
    /// `next_offset` was within the dispatched ceiling — the normal case.
    WithinDispatch,
    /// `next_offset` exceeded the ceiling and was capped to it: the worker tried to commit past an
    /// offset never routed to it (dropped buffer or worker accounting bug). An F1 invariant alert.
    CappedAheadOfDispatch,
}

/// Thread-safe `partition → `[`PartitionProgress`], sharded behind `DashMap` so per-partition
/// updates from different worker tasks don't contend on one lock.
#[derive(Debug, Default)]
pub struct OffsetTracker {
    partitions: DashMap<i32, PartitionProgress>,
}

impl OffsetTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Raise the per-partition dispatch ceiling. The [`EventDispatcher`] calls this for every routed
    /// message **before** routing, with `next_offset = message_offset + 1`. Monotonic. Recording
    /// the handoff is what lets [`mark_processed`](Self::mark_processed) refuse to commit past an
    /// offset that was consumed but never dispatched.
    ///
    /// [`EventDispatcher`]: crate::consumers::events::EventDispatcher
    pub fn mark_dispatched(&self, partition: i32, next_offset: i64) {
        let mut progress = self.partitions.entry(partition).or_default();
        progress.dispatched_offset = progress.dispatched_offset.max(next_offset);
    }

    /// Record the next offset to consume (`last processed + 1`) after a batch is durably processed.
    /// Monotonic, and clamped to [`dispatched_offset`](PartitionProgress::dispatched_offset) so a
    /// worker can't advance the committed position past an offset it wasn't dispatched. The clamp is
    /// a no-op in correct operation ([`MarkOutcome::WithinDispatch`]); a clamp that bites returns
    /// [`MarkOutcome::CappedAheadOfDispatch`].
    #[must_use = "a CappedAheadOfDispatch outcome is an F1 invariant violation the worker must surface"]
    pub fn mark_processed(&self, partition: i32, next_offset: i64) -> MarkOutcome {
        let mut progress = self.partitions.entry(partition).or_default();
        progress.mark_processed(next_offset)
    }

    /// Pin this partition's committable offset at the consumed message's own `offset` until the
    /// returned token is passed to [`complete_deferred`](Self::complete_deferred).
    ///
    /// This is for durable work that continues after the message handler returns. Later processed
    /// marks may advance normally, but Kafka cannot commit past the earliest deferred offset. The
    /// serial partition worker must defer each consumed offset at most once per tenure.
    pub fn defer(&self, partition: i32, offset: i64) -> DeferredOffset {
        let mut progress = self.partitions.entry(partition).or_default();
        assert!(
            progress.deferred.insert(offset),
            "partition {partition} offset {offset} was deferred twice in one tenure",
        );
        DeferredOffset {
            partition,
            offset,
            tenure: Arc::clone(&progress.tenure),
        }
    }

    /// Release a deferred floor and mark its consumed message processed (`offset + 1`).
    ///
    /// Returns `None` when the partition was forgotten or the token no longer belongs to its
    /// current progress. This makes late completion after a rebalance harmless and avoids
    /// recreating tracking state for a revoked partition.
    pub fn complete_deferred(&self, deferred: DeferredOffset) -> Option<MarkOutcome> {
        let mut progress = self.partitions.get_mut(&deferred.partition)?;
        if !Arc::ptr_eq(&progress.tenure, &deferred.tenure)
            || !progress.deferred.remove(&deferred.offset)
        {
            return None;
        }
        Some(progress.mark_processed(deferred.offset + 1))
    }

    /// Atomically replace one deferred floor with another and mark the superseded message processed.
    ///
    /// Keeping both mutations under the partition lock matters when the replacement reuses an
    /// offset after a follower rewind: a concurrent commit snapshot must never observe the old floor
    /// removed before the replacement is installed. Returns `None` when the token belongs to a
    /// forgotten tenure or no longer owns its floor.
    pub fn replace_deferred(
        &self,
        deferred: DeferredOffset,
        replacement_offset: i64,
    ) -> Option<(DeferredOffset, MarkOutcome)> {
        let mut progress = self.partitions.get_mut(&deferred.partition)?;
        if !Arc::ptr_eq(&progress.tenure, &deferred.tenure)
            || !progress.deferred.remove(&deferred.offset)
        {
            return None;
        }
        assert!(
            progress.deferred.insert(replacement_offset),
            "partition {} offset {replacement_offset} was deferred twice in one tenure",
            deferred.partition,
        );
        let outcome = progress.mark_processed(deferred.offset + 1);
        let replacement = DeferredOffset {
            partition: deferred.partition,
            offset: replacement_offset,
            tenure: Arc::clone(&progress.tenure),
        };
        Some((replacement, outcome))
    }

    /// Pin the partition's commit floor at `offset` (the failed message's *own* offset `K`, **not**
    /// `K + 1`), so [`committable_offsets`](Self::committable_offsets) never advances past it and Kafka
    /// redelivers the message. Used when a handler step failed and the only recovery is replay (a
    /// store write that held the last copy of merge/transfer state, a forward produce with no local
    /// outbox); contrast [`mark_processed`](Self::mark_processed), which advances *past* `K`.
    ///
    /// A hold only ever **lowers** the floor ([`min`] of any existing hold): two failures in one
    /// tenure pin the earlier message, and a hold can never *raise* a floor a prior failure already
    /// set. The hold is sticky for the tenure — see [`held_offset`](PartitionProgress::held_offset).
    /// Returns the resulting floor so the caller can report it: the floor (not the raw `offset`) is
    /// the position that will actually be redelivered, so it's what a `held_offset` gauge should show.
    pub fn hold(&self, partition: i32, offset: i64) -> i64 {
        let mut progress = self.partitions.entry(partition).or_default();
        let floor = progress
            .held_offset
            .map_or(offset, |existing| existing.min(offset));
        progress.held_offset = Some(floor);
        floor
    }

    /// Mark an offset as acked-committed by Kafka. Monotonic, and a no-op for a never-processed
    /// partition (you cannot commit what you have not consumed).
    pub fn mark_committed(&self, partition: i32, offset: i64) {
        if let Some(mut progress) = self.partitions.get_mut(&partition) {
            progress.committed_offset = progress.committed_offset.max(offset);
        }
    }

    /// Snapshot of `partition → next-offset-to-consume` for every partition with a *processed*
    /// offset, capped at the earliest sticky [`hold`](Self::hold) or releasable
    /// [`defer`](Self::defer) floor. Partitions tracked only because they were dispatched or deferred
    /// carry the `processed_offset == 0` sentinel and are excluded — nothing safe to commit, so
    /// Kafka replays them. A real mark is always `≥ 1`, so the filter never drops a committable
    /// offset.
    ///
    /// Floors cap the *value*, not the filter: a floor pinned at the message's own offset `K` makes
    /// the committable value `min(processed, K)` so a later success cannot leapfrog the unfinished
    /// message. A floor at `0` (or any floor while `processed == 0`) yields no committable value, so
    /// Kafka replays from the start of the uncommitted range.
    pub fn committable_offsets(&self) -> HashMap<i32, i64> {
        self.partitions
            .iter()
            .filter_map(|entry| {
                entry
                    .value()
                    .committable_offset()
                    .map(|offset| (*entry.key(), offset))
            })
            .collect()
    }

    pub fn committed_offset(&self, partition: i32) -> Option<i64> {
        self.partitions.get(&partition).map(|p| p.committed_offset)
    }

    /// Drop all tracking for a revoked partition. Its offset should already be committed. Removing the
    /// whole entry also clears any [`hold`](Self::hold) and [`defer`](Self::defer) floors, so the next
    /// tenure starts unheld and replays from the committed offset — the only way a sticky hold is
    /// released.
    pub fn forget_partition(&self, partition: i32) {
        self.partitions.remove(&partition);
    }

    pub fn partition_count(&self) -> usize {
        self.partitions.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mark_processed_advances_and_never_regresses() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(5, 150);

        assert_eq!(tracker.mark_processed(5, 100), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&5), Some(&100));

        // A lower offset (replay) must not regress progress.
        assert_eq!(tracker.mark_processed(5, 50), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&5), Some(&100));

        assert_eq!(tracker.mark_processed(5, 150), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&5), Some(&150));
    }

    #[test]
    fn mark_processed_is_clamped_to_the_dispatched_ceiling() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(3, 100);

        assert_eq!(
            tracker.mark_processed(3, 500),
            MarkOutcome::CappedAheadOfDispatch,
        );
        assert_eq!(tracker.committable_offsets().get(&3), Some(&100));

        assert_eq!(tracker.mark_processed(3, 80), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&3), Some(&100));
    }

    #[test]
    fn mark_processed_with_no_dispatch_commits_nothing() {
        // Route error: nothing was dispatched, so the mark clamps to the `0` sentinel and Kafka
        // replays it.
        let tracker = OffsetTracker::new();
        assert_eq!(
            tracker.mark_processed(9, 101),
            MarkOutcome::CappedAheadOfDispatch,
        );
        assert_eq!(tracker.committable_offsets().get(&9), None);
        // Still tracked (ceiling 0), just not committable.
        assert_eq!(tracker.partition_count(), 1);
    }

    #[test]
    fn dispatched_ceiling_is_monotonic() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(1, 50);
        tracker.mark_dispatched(1, 200);
        // A lower dispatch (out-of-order routing) never lowers the ceiling.
        tracker.mark_dispatched(1, 30);

        assert_eq!(tracker.mark_processed(1, 200), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&1), Some(&200));
        assert_eq!(
            tracker.mark_processed(1, 201),
            MarkOutcome::CappedAheadOfDispatch,
        );
        assert_eq!(tracker.committable_offsets().get(&1), Some(&200));
    }

    #[test]
    fn committable_offsets_snapshots_every_processed_partition() {
        let tracker = OffsetTracker::new();
        for (partition, next) in [(0, 10), (1, 20), (2, 30)] {
            tracker.mark_dispatched(partition, next);
            assert_eq!(
                tracker.mark_processed(partition, next),
                MarkOutcome::WithinDispatch,
            );
        }

        let snapshot = tracker.committable_offsets();
        assert_eq!(snapshot.len(), 3);
        assert_eq!(snapshot.get(&0), Some(&10));
        assert_eq!(snapshot.get(&1), Some(&20));
        assert_eq!(snapshot.get(&2), Some(&30));
    }

    #[test]
    fn mark_committed_advances_monotonically_only_for_known_partitions() {
        let tracker = OffsetTracker::new();

        // Committing an unprocessed partition is a no-op.
        tracker.mark_committed(7, 100);
        assert_eq!(tracker.committed_offset(7), None);

        tracker.mark_dispatched(7, 200);
        assert_eq!(tracker.mark_processed(7, 200), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committed_offset(7), Some(0));

        tracker.mark_committed(7, 150);
        assert_eq!(tracker.committed_offset(7), Some(150));

        // Backward commit ignored, forward advances.
        tracker.mark_committed(7, 100);
        assert_eq!(tracker.committed_offset(7), Some(150));
        tracker.mark_committed(7, 200);
        assert_eq!(tracker.committed_offset(7), Some(200));
    }

    #[test]
    fn forget_partition_drops_only_that_partition() {
        let tracker = OffsetTracker::new();
        for (partition, next) in [(0, 10), (1, 20)] {
            tracker.mark_dispatched(partition, next);
            let _ = tracker.mark_processed(partition, next);
        }

        tracker.forget_partition(0);

        assert_eq!(tracker.partition_count(), 1);
        assert_eq!(tracker.committable_offsets().get(&0), None);
        assert_eq!(tracker.committable_offsets().get(&1), Some(&20));
    }

    #[test]
    fn a_hold_pins_committable_and_a_later_success_cannot_leapfrog_it() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 44);

        // A failed message at offset 41 holds at its own offset (no +1).
        tracker.hold(4, 41);
        assert_eq!(tracker.mark_processed(4, 43), MarkOutcome::WithinDispatch);

        assert_eq!(tracker.committable_offsets().get(&4), Some(&41));
    }

    #[test]
    fn a_hold_only_lowers_the_floor_never_raises_it() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let _ = tracker.mark_processed(4, 60);

        tracker.hold(4, 41);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&41));

        // A second, higher hold cannot raise the floor — the earlier failed message still gates it.
        tracker.hold(4, 50);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&41));

        tracker.hold(4, 30);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&30));
    }

    #[test]
    fn forget_partition_clears_a_hold() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let _ = tracker.mark_processed(4, 60);
        tracker.hold(4, 41);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&41));

        // The next tenure starts unheld: forget drops the entry (hold included), and a fresh mark
        // commits normally.
        tracker.forget_partition(4);
        tracker.mark_dispatched(4, 100);
        let _ = tracker.mark_processed(4, 60);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&60));
    }

    #[test]
    fn a_hold_at_offset_zero_commits_nothing_so_kafka_redelivers_it() {
        // The very first message (offset 0) failing must not let a later success commit past it.
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 10);
        tracker.hold(4, 0);
        let _ = tracker.mark_processed(4, 5);

        // min(processed=5, held=0) = 0, which the `> 0` filter excludes → nothing committable →
        // Kafka replays from 0 and redelivers the held message.
        assert_eq!(tracker.committable_offsets().get(&4), None);
    }

    #[test]
    fn a_hold_while_processed_is_zero_commits_nothing() {
        // A failure before any success on the partition: the `processed == 0` sentinel already blocks
        // the commit; the hold does not change that (and does not panic on the absent processed mark).
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 10);
        tracker.hold(4, 3);

        assert_eq!(tracker.committable_offsets().get(&4), None);
        assert_eq!(tracker.partition_count(), 1);
    }

    #[test]
    fn later_processed_marks_cannot_leapfrog_a_deferred_offset() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let deferred = tracker.defer(4, 41);

        assert_eq!(tracker.mark_processed(4, 80), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&41));

        assert_eq!(
            tracker.complete_deferred(deferred),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&80));
    }

    #[test]
    fn completing_a_deferred_offset_zero_marks_next_offset_one() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 1);
        let deferred = tracker.defer(4, 0);

        assert_eq!(tracker.committable_offsets().get(&4), None);
        assert_eq!(
            tracker.complete_deferred(deferred),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&1));
    }

    #[test]
    fn multiple_deferred_offsets_reveal_the_next_lowest_floor() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let first = tracker.defer(4, 20);
        let second = tracker.defer(4, 40);
        let _ = tracker.mark_processed(4, 80);

        assert_eq!(tracker.committable_offsets().get(&4), Some(&20));
        assert_eq!(
            tracker.complete_deferred(first),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&40));
        assert_eq!(
            tracker.complete_deferred(second),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&80));

        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let first = tracker.defer(4, 20);
        let second = tracker.defer(4, 40);
        let _ = tracker.mark_processed(4, 80);

        assert_eq!(
            tracker.complete_deferred(second),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&20));
        assert_eq!(
            tracker.complete_deferred(first),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&80));
    }

    #[test]
    fn replacing_a_deferred_offset_never_exposes_an_unpinned_commit() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let original = tracker.defer(4, 20);
        let _ = tracker.mark_processed(4, 80);

        let (replacement, outcome) = tracker
            .replace_deferred(original, 20)
            .expect("the current tenure owns the original floor");

        assert_eq!(outcome, MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&20));
        assert_eq!(
            tracker.complete_deferred(replacement),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&80));
    }

    #[test]
    fn replacing_a_deferred_offset_moves_the_floor_atomically() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let original = tracker.defer(4, 40);
        let _ = tracker.mark_processed(4, 80);

        let (replacement, _) = tracker
            .replace_deferred(original, 20)
            .expect("the current tenure owns the original floor");

        assert_eq!(tracker.committable_offsets().get(&4), Some(&20));
        assert_eq!(
            tracker.complete_deferred(replacement),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&80));
    }

    #[test]
    fn deferred_and_sticky_floors_compose_by_minimum() {
        for (partition, held, deferred_offset, expected_before, expected_after) in
            [(1, 30, 40, 30, 30), (2, 50, 40, 40, 50)]
        {
            let tracker = OffsetTracker::new();
            tracker.mark_dispatched(partition, 100);
            tracker.hold(partition, held);
            let deferred = tracker.defer(partition, deferred_offset);
            let _ = tracker.mark_processed(partition, 80);

            assert_eq!(
                tracker.committable_offsets().get(&partition),
                Some(&expected_before),
            );
            assert_eq!(
                tracker.complete_deferred(deferred),
                Some(MarkOutcome::WithinDispatch),
            );
            assert_eq!(
                tracker.committable_offsets().get(&partition),
                Some(&expected_after),
            );
        }
    }

    #[test]
    fn forgetting_a_partition_invalidates_its_deferred_tokens() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let stale = tracker.defer(4, 40);
        let _ = tracker.mark_processed(4, 80);
        tracker.forget_partition(4);

        // Recreate the same offset in a new tenure to pin the ABA case: the stale token cannot
        // release work now owned by the new partition worker.
        tracker.mark_dispatched(4, 100);
        let current = tracker.defer(4, 40);
        let _ = tracker.mark_processed(4, 80);
        assert_eq!(tracker.complete_deferred(stale), None);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&40));

        assert_eq!(
            tracker.complete_deferred(current),
            Some(MarkOutcome::WithinDispatch),
        );
        assert_eq!(tracker.committable_offsets().get(&4), Some(&80));
    }

    #[test]
    fn dropping_a_deferred_token_pins_until_the_partition_is_forgotten() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(4, 100);
        let deferred = tracker.defer(4, 40);
        let _ = tracker.mark_processed(4, 80);

        drop(deferred);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&40));

        tracker.forget_partition(4);
        tracker.mark_dispatched(4, 100);
        let _ = tracker.mark_processed(4, 80);
        assert_eq!(tracker.committable_offsets().get(&4), Some(&80));
    }

    #[test]
    #[should_panic(expected = "offset 40 was deferred twice in one tenure")]
    fn deferring_the_same_offset_twice_fails_closed() {
        let tracker = OffsetTracker::new();
        let _first = tracker.defer(4, 40);
        let _second = tracker.defer(4, 40);
    }
}
