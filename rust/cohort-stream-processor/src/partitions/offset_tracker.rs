//! Offset-tracking primitives (TDD §2.5, §4.1.1). Two independent concerns live here, each
//! unit-tested on its own:
//!
//! 1. [`OffsetTracker`] — *per-partition* commit tracking, lifted and slimmed from
//!    `kafka-deduplicator/src/kafka/offset_tracker.rs`. It records the next offset to consume
//!    after a partition's batch is durably processed (the value PR 1.7's commit loop will read
//!    from [`OffsetTracker::committable_offsets`]) and the offset Kafka last acked as committed
//!    (the true recovery point on restart). Deliberately *not* ported yet: dedup's rebalance gate
//!    (PR 1.7), producer-offset tracking (PR 1.8), and batch-ID ordering checks — ordering within
//!    a partition is already guaranteed by the single per-partition channel plus the serial worker
//!    (PR 1.6), so the out-of-order batch detection has no job to do in M1.
//!
//! 2. [`is_replay`] — the *per-key* replay primitive, and the load-bearing half of the PR 1.5
//!    acceptance. RocksDB counter increments like `BehavioralDailyBuckets.buckets[i] += 1` are not
//!    idempotent, so on Kafka replay an already-applied increment must be skipped. PR 1.6's
//!    `StatefulRecord` persists the last-applied `(partition, offset)` per key (§4.1.1) and calls
//!    this before folding an event in. Keeping it a free function (no `self`) makes it pure and
//!    trivially testable, with no coupling to the store.

use std::collections::HashMap;

use dashmap::DashMap;

/// Per-partition consume/commit progress.
///
/// Slimmed from dedup's `PartitionState`: no `producer_offset` (PR 1.8 output topic), no
/// `last_processed_batch_id` (ordering is the channel's job, not the tracker's — decision 3),
/// and no rebalance coupling (PR 1.7).
#[derive(Debug, Default, Clone, Copy)]
struct PartitionProgress {
    /// Next offset to consume — highest processed offset `+ 1`. This is the value committed to
    /// Kafka, and it never moves backward (a replayed or out-of-order batch can't regress it).
    /// `0` is the "never processed" sentinel: a real mark is always `≥ 1` (last processed offset
    /// `+ 1`), so [`committable_offsets`](OffsetTracker::committable_offsets) treats `0` as
    /// "nothing to commit" — see [`mark_dispatched`](OffsetTracker::mark_dispatched).
    processed_offset: i64,
    /// Highest `next-offset` the dispatcher has actually routed to a worker (the F1 ceiling).
    /// [`mark_processed`](OffsetTracker::mark_processed) clamps `processed_offset` to never exceed
    /// this, so an offset that was *consumed but never dispatched* (a dropped buffer, a route
    /// error) can never be committed past. In correct operation `dispatched_offset` is exactly the
    /// max routed offset `+ 1`, so the clamp is a no-op; it only bites on a regression.
    dispatched_offset: i64,
    /// Last offset Kafka acked as committed. Tracked separately from `processed_offset` because
    /// the gap between "processed locally" and "committed to Kafka" is exactly the window Kafka
    /// replays after a crash. Used for checkpointing by later PRs.
    committed_offset: i64,
}

/// What [`OffsetTracker::mark_processed`] did with a worker's offset mark — returned so the worker
/// can surface the F1 invariant violation as a metric without the tracker importing `metrics`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MarkOutcome {
    /// `next_offset` was within the dispatched ceiling — the normal case. (Whether or not it
    /// advanced `processed_offset`; a lower-or-equal value is still "within".)
    WithinDispatch,
    /// `next_offset` exceeded the dispatched ceiling and was capped to it. The worker tried to
    /// commit past an offset that was never routed to it — the F1 dropped-buffer signature, or a
    /// worker offset-accounting bug. The worker emits `cohort_stream_offset_ahead_of_dispatch_total`.
    CappedAheadOfDispatch,
}

/// Thread-safe map of `partition → `[`PartitionProgress`].
///
/// Sharded behind `DashMap` so per-partition updates from different worker tasks don't contend on
/// a single lock. Reads and writes are independent per partition.
#[derive(Debug, Default)]
pub struct OffsetTracker {
    partitions: DashMap<i32, PartitionProgress>,
}

impl OffsetTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Raise the per-partition dispatch ceiling. Called by the [`EventDispatcher`] for every routed
    /// message **before** it routes the batch, with `next_offset = message_offset + 1`.
    ///
    /// Monotonic (a lower value never lowers the ceiling). This is the F1 defense-in-depth: it
    /// records that the dispatcher actually handed the offset to a worker, so a later
    /// [`mark_processed`](Self::mark_processed) cannot advance the committed position past an offset
    /// that was consumed but never dispatched (a dropped consume buffer, a route error).
    ///
    /// [`EventDispatcher`]: crate::consumers::events::EventDispatcher
    pub fn mark_dispatched(&self, partition: i32, next_offset: i64) {
        let mut progress = self.partitions.entry(partition).or_default();
        progress.dispatched_offset = progress.dispatched_offset.max(next_offset);
    }

    /// Record the next offset to consume after a partition's batch is durably processed.
    ///
    /// `next_offset` is the last processed offset `+ 1`. Monotonic: a lower value (a replayed or
    /// late-arriving batch) is ignored, so progress only ever advances. **Clamped** to the
    /// partition's [`dispatched_offset`](PartitionProgress::dispatched_offset): a worker can never
    /// advance the committed position past an offset the dispatcher did not route to it. In correct
    /// operation the worker only ever marks offsets it was dispatched, so the clamp is a no-op and
    /// the result is [`MarkOutcome::WithinDispatch`]; a clamp that actually bites returns
    /// [`MarkOutcome::CappedAheadOfDispatch`] for the caller to alert on (the F1 signature).
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

    /// Mark an offset as acked-committed by Kafka. Monotonic, and a no-op for a partition that was
    /// never processed (you cannot commit what you have not consumed) — mirrors dedup's
    /// `and_modify`-without-insert semantics.
    pub fn mark_committed(&self, partition: i32, offset: i64) {
        if let Some(mut progress) = self.partitions.get_mut(&partition) {
            progress.committed_offset = progress.committed_offset.max(offset);
        }
    }

    /// Snapshot of `partition → next-offset-to-consume` for every partition with a *processed*
    /// offset. The commit loop turns this into the `TopicPartitionList` it commits to Kafka.
    ///
    /// Partitions tracked only because they were *dispatched* (their worker has not yet marked an
    /// offset, or — the F1/route-error case — never will) carry the `processed_offset == 0`
    /// sentinel and are excluded: there is nothing safe to commit for them, so Kafka replays from
    /// the last committed offset. A real processed mark is always `≥ 1`, so this filter never drops
    /// a legitimately committable offset.
    pub fn committable_offsets(&self) -> HashMap<i32, i64> {
        self.partitions
            .iter()
            .filter(|entry| entry.value().processed_offset > 0)
            .map(|entry| (*entry.key(), entry.value().processed_offset))
            .collect()
    }

    /// Last offset Kafka acked as committed for `partition`, if tracked.
    pub fn committed_offset(&self, partition: i32) -> Option<i64> {
        self.partitions.get(&partition).map(|p| p.committed_offset)
    }

    /// Drop all tracking for a partition — called when the partition is revoked. The offset
    /// should already have been committed before this point.
    pub fn forget_partition(&self, partition: i32) {
        self.partitions.remove(&partition);
    }

    /// Number of partitions currently tracked.
    pub fn partition_count(&self) -> usize {
        self.partitions.len()
    }
}

/// `true` ⇒ this `(partition, offset)` was already folded into the key's state, so the caller must
/// **skip** the (non-idempotent) increment.
///
/// Replay is detected only within the *same* source partition: an offset `≤` the last-applied one
/// is a duplicate. A *different* source partition is never treated as a replay — after a rebalance
/// or a shuffler re-key a key may legitimately begin receiving a new source partition, whose
/// offsets are unrelated to the old partition's and must all be applied.
///
/// PR 1.6 feeds this the upstream coordinates carried on the event
/// ([`CohortStreamEvent::source_partition`][src_p] / [`source_offset`][src_o]) and the
/// last-applied pair persisted on `StatefulRecord` (§4.1.1) — **not** the `cohort_stream_events`
/// offset, which changes on every reshuffle and so cannot anchor idempotence. A first-ever apply
/// (no prior state) is handled by PR 1.6 *not calling* this, or by passing a sentinel `last_offset`
/// below any real offset; either way the function's "different partition ⇒ apply, lower-or-equal
/// same-partition offset ⇒ skip" rule does the right thing.
///
/// TODO(PR 2.1): because this dedups only within one source partition and `StatefulRecord` stores a
/// single last-applied pair, a person whose events span multiple source partitions (the shuffler
/// re-keys by person) is not fully replay-deduped across partitions. Idempotent in M1; PR 2.1's
/// bucket increments are not — see [`crate::stage1::state::StatefulRecord`] and TDD §10 L11.
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
        // The key last applied an event at source partition 5, offset 100.
        let (last_partition, last_offset) = (5, 100);

        // (msg_partition, msg_offset, expected_is_replay, why)
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
        // PR 1.6 may seed last_offset = -1 ("nothing applied yet") on the same partition.
        assert!(!is_replay(5, -1, 5, 0), "offset 0 > sentinel -1 → apply");
        assert!(
            is_replay(5, -1, 5, -1),
            "re-seeing the sentinel itself → skip"
        );
    }

    #[test]
    fn mark_processed_advances_and_never_regresses() {
        let tracker = OffsetTracker::new();

        // The dispatcher raises the ceiling before the worker processes anything.
        tracker.mark_dispatched(5, 150);

        assert_eq!(tracker.mark_processed(5, 100), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&5), Some(&100));

        // A lower offset (replay / out-of-order batch) must not move progress backward.
        assert_eq!(tracker.mark_processed(5, 50), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&5), Some(&100));

        // A higher offset (still within the ceiling) advances it.
        assert_eq!(tracker.mark_processed(5, 150), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&5), Some(&150));
    }

    #[test]
    fn mark_processed_is_clamped_to_the_dispatched_ceiling() {
        let tracker = OffsetTracker::new();

        // Only offsets up to 99 (next-offset 100) were ever dispatched to the worker.
        tracker.mark_dispatched(3, 100);

        // A worker that tries to commit past the ceiling is capped to it and flagged — the F1
        // invariant violation. The committed position never advances past undispatched offsets.
        assert_eq!(
            tracker.mark_processed(3, 500),
            MarkOutcome::CappedAheadOfDispatch,
        );
        assert_eq!(tracker.committable_offsets().get(&3), Some(&100));

        // Re-marking within the (unchanged) ceiling is a no-op and not flagged.
        assert_eq!(tracker.mark_processed(3, 80), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&3), Some(&100));
    }

    #[test]
    fn mark_processed_with_no_dispatch_commits_nothing() {
        // A worker mark on a partition the dispatcher never raised a ceiling for (a route error:
        // the message reached no worker, so it was never dispatched) clamps to the `0` sentinel and
        // is excluded from the committable snapshot — Kafka replays it.
        let tracker = OffsetTracker::new();
        assert_eq!(
            tracker.mark_processed(9, 101),
            MarkOutcome::CappedAheadOfDispatch,
        );
        assert_eq!(tracker.committable_offsets().get(&9), None);
        // The partition is still tracked (it has a ceiling of 0), just not committable.
        assert_eq!(tracker.partition_count(), 1);
    }

    #[test]
    fn dispatched_ceiling_is_monotonic() {
        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(1, 50);
        tracker.mark_dispatched(1, 200);
        // A lower dispatch (out-of-order routing) never lowers the ceiling.
        tracker.mark_dispatched(1, 30);

        // A worker may now mark up to 200.
        assert_eq!(tracker.mark_processed(1, 200), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committable_offsets().get(&1), Some(&200));
        // But not past it.
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

        // Committing an unprocessed partition is a no-op (nothing to commit).
        tracker.mark_committed(7, 100);
        assert_eq!(tracker.committed_offset(7), None);

        tracker.mark_dispatched(7, 200);
        assert_eq!(tracker.mark_processed(7, 200), MarkOutcome::WithinDispatch);
        assert_eq!(tracker.committed_offset(7), Some(0));

        tracker.mark_committed(7, 150);
        assert_eq!(tracker.committed_offset(7), Some(150));

        // Backward commit is ignored; forward commit advances.
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
