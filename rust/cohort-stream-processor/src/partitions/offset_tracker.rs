//! Offset-tracking primitives. Two independent concerns, each unit-tested on its own:
//!
//! 1. [`OffsetTracker`] — per-partition commit tracking: the next offset to consume after a
//!    partition's batch is durably processed ([`OffsetTracker::committable_offsets`]) and the
//!    offset Kafka last acked (the recovery point on restart). No batch-ID ordering checks: the
//!    single per-partition channel plus serial worker already guarantee in-partition order.
//!
//! 2. [`is_replay`] — the per-key replay primitive. Counter increments aren't idempotent, so a
//!    replayed offset already folded into a key's state must be skipped.

use std::collections::HashMap;

use dashmap::DashMap;

/// Per-partition consume/commit progress.
#[derive(Debug, Default, Clone, Copy)]
struct PartitionProgress {
    /// Next offset to consume (highest processed `+ 1`), the value committed to Kafka. Monotonic.
    /// `0` is the "never processed" sentinel; a real mark is always `≥ 1`, so
    /// [`committable_offsets`](OffsetTracker::committable_offsets) treats `0` as nothing to commit.
    processed_offset: i64,
    /// Dispatch ceiling: highest next-offset actually routed to a worker.
    /// [`mark_processed`](OffsetTracker::mark_processed) clamps `processed_offset` to this so a
    /// consumed-but-never-dispatched offset (dropped buffer, route error) can't be committed past.
    /// In correct operation it equals the max routed offset `+ 1`, so the clamp only bites on a bug.
    dispatched_offset: i64,
    /// Last offset Kafka acked as committed. The gap to `processed_offset` is the window Kafka
    /// replays after a crash.
    committed_offset: i64,
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
        let capped = next_offset.min(progress.dispatched_offset);
        progress.processed_offset = progress.processed_offset.max(capped);
        if capped < next_offset {
            MarkOutcome::CappedAheadOfDispatch
        } else {
            MarkOutcome::WithinDispatch
        }
    }

    /// Mark an offset as acked-committed by Kafka. Monotonic, and a no-op for a never-processed
    /// partition (you cannot commit what you have not consumed).
    pub fn mark_committed(&self, partition: i32, offset: i64) {
        if let Some(mut progress) = self.partitions.get_mut(&partition) {
            progress.committed_offset = progress.committed_offset.max(offset);
        }
    }

    /// Snapshot of `partition → next-offset-to-consume` for every partition with a *processed*
    /// offset. Partitions tracked only because they were dispatched carry the `processed_offset == 0`
    /// sentinel and are excluded — nothing safe to commit, so Kafka replays them. A real mark is
    /// always `≥ 1`, so the filter never drops a committable offset.
    pub fn committable_offsets(&self) -> HashMap<i32, i64> {
        self.partitions
            .iter()
            .filter(|entry| entry.value().processed_offset > 0)
            .map(|entry| (*entry.key(), entry.value().processed_offset))
            .collect()
    }

    pub fn committed_offset(&self, partition: i32) -> Option<i64> {
        self.partitions.get(&partition).map(|p| p.committed_offset)
    }

    /// Drop all tracking for a revoked partition. Its offset should already be committed.
    pub fn forget_partition(&self, partition: i32) {
        self.partitions.remove(&partition);
    }

    pub fn partition_count(&self) -> usize {
        self.partitions.len()
    }
}

/// `true` ⇒ this `(partition, offset)` was already folded into the key's state, so the caller must
/// **skip** the (non-idempotent) increment.
///
/// Replay is detected only within the *same* source partition (offset `≤` last-applied). A
/// different source partition is never a replay: after a rebalance/re-key a key may begin receiving
/// a new partition whose offsets are unrelated and must all apply. The caller feeds the upstream
/// coordinates ([`source_partition`][src_p] / [`source_offset`][src_o]), **not** the
/// `cohort_stream_events` offset, which changes on every reshuffle.
///
/// Known limitation: with a single last-applied pair per `StatefulRecord`, a person whose events
/// span multiple source partitions is not fully replay-deduped across them.
///
/// [src_p]: crate::consumers::events::CohortStreamEvent::source_partition
/// [src_o]: crate::consumers::events::CohortStreamEvent::source_offset
pub fn is_replay(
    last_partition: i32,
    last_offset: i64,
    msg_partition: i32,
    msg_offset: i64,
) -> bool {
    last_partition == msg_partition && msg_offset <= last_offset
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_replay_blocks_only_same_partition_at_or_below_last_offset() {
        let (last_partition, last_offset) = (5, 100);

        let cases = [
            (5, 100, true, "exact offset is already applied → skip"),
            (
                5,
                99,
                true,
                "lower offset on the same partition is a replay → skip",
            ),
            (
                5,
                101,
                false,
                "higher offset on the same partition is new → apply",
            ),
            (
                6,
                50,
                false,
                "different partition is never a replay → apply",
            ),
            (
                6,
                100,
                false,
                "different partition, equal offset, still applies",
            ),
            (
                6,
                0,
                false,
                "different partition, lowest offset, still applies",
            ),
        ];

        for (msg_partition, msg_offset, expected, why) in cases {
            assert_eq!(
                is_replay(last_partition, last_offset, msg_partition, msg_offset),
                expected,
                "is_replay({last_partition}, {last_offset}, {msg_partition}, {msg_offset}): {why}",
            );
        }
    }

    #[test]
    fn is_replay_handles_a_below_range_sentinel_last_offset() {
        // `last_offset = -1` seeds "nothing applied yet".
        assert!(!is_replay(5, -1, 5, 0), "offset 0 > sentinel -1 → apply");
        assert!(
            is_replay(5, -1, 5, -1),
            "re-seeing the sentinel itself → skip"
        );
    }

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

        // A worker marking past the ceiling is capped to it and flagged.
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
}
