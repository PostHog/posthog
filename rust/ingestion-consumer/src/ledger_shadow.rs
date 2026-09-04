//! Shadow-mode verification of the offset ledger: compares the frontier the
//! ledger reaches with the commit the consumer calculates today, and carries
//! the ledger's metric vocabulary.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use common_kafka_consumer::{
    Charge, Held, Offset, Rejection, Settlement, TopicOffsetLedger, TopicPartition,
};
use metrics::{counter, gauge};
use tracing::{info, warn};

use crate::order_sentinel::OffsetSpan;

/// Runs the offset ledger next to the current commit path without taking
/// part in commit choice. Without a ledger every call is a no-op: the off
/// mode leaves the consumer with no ledger at all, so nothing is charged,
/// settled, or forgotten anywhere.
pub(crate) struct LedgerShadow {
    ledger: Option<Arc<TopicOffsetLedger>>,
    /// Partitions whose frontier disagrees with the commit, by the ledger
    /// generation the disagreement was seen under. A persistent disagreement
    /// logs when it starts and when it ends, not on every batch.
    mismatched: Mutex<HashMap<TopicPartition, u64>>,
}

impl LedgerShadow {
    pub(crate) fn new(ledger: Option<Arc<TopicOffsetLedger>>) -> Self {
        Self {
            ledger,
            mismatched: Mutex::new(HashMap::new()),
        }
    }

    /// See [`TopicOffsetLedger::generations_version`]; constant without a
    /// ledger.
    pub(crate) fn generations_version(&self) -> u64 {
        let Some(ledger) = &self.ledger else {
            return 0;
        };
        ledger.generations_version()
    }

    /// See [`TopicOffsetLedger::generation`]; 0 without a ledger.
    pub(crate) fn generation(&self, topic_partition: &TopicPartition) -> u64 {
        let Some(ledger) = &self.ledger else {
            return 0;
        };
        ledger.generation(topic_partition)
    }

    /// Charge one batch's slice of a partition to its ledger and publish what
    /// the partition's window holds.
    pub(crate) fn charge(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        charges: &[(Offset, Charge)],
    ) {
        let Some(ledger) = &self.ledger else {
            return;
        };
        match ledger.charge(topic_partition, stamp, charges.iter().copied()) {
            Ok(held) => set_held_gauges(&topic_partition.topic, topic_partition.partition, held),
            Err(rejection) => count_rejection(
                "charge",
                topic_partition,
                rejection,
                RejectedSlice::charged(charges),
            ),
        }
    }

    /// Settle one batch's slice of a partition: complete its offsets and
    /// compare the frontier with the commit the batch submits. Returns the
    /// settlement, or `None` when the ledger rejected the slice. The window
    /// holds the offsets until `drain`.
    pub(crate) fn settle(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        offsets: impl IntoIterator<Item = Offset>,
        span: &OffsetSpan,
    ) -> Option<Settlement> {
        let Some(ledger) = &self.ledger else {
            return None;
        };
        let settlement = match ledger.settle(topic_partition, stamp, offsets) {
            Ok(settlement) => settlement,
            Err(rejection) => {
                count_rejection(
                    "settle",
                    topic_partition,
                    rejection,
                    RejectedSlice::settled(span),
                );
                return None;
            }
        };
        self.observe(topic_partition, &settlement, span, stamp);
        Some(settlement)
    }

    /// Drain a settled partition's completed prefix and publish what its
    /// window still holds.
    pub(crate) fn drain(&self, topic_partition: &TopicPartition) {
        let Some(ledger) = &self.ledger else {
            return;
        };
        ledger.take_frontier(topic_partition);
        set_held_gauges(
            &topic_partition.topic,
            topic_partition.partition,
            ledger.held(topic_partition),
        );
    }

    /// Count every disagreement; log only the batch that starts one and the
    /// batch that ends it.
    fn observe(
        &self,
        topic_partition: &TopicPartition,
        settlement: &Settlement,
        span: &OffsetSpan,
        stamp: u64,
    ) {
        let mut mismatched = self.mismatched.lock().unwrap();
        let Some(mismatch) = frontier_mismatch(topic_partition, settlement.frontier, span) else {
            if mismatched.remove(topic_partition).is_some() {
                info!(
                    topic = %topic_partition.topic,
                    partition = topic_partition.partition,
                    committed = span.last + 1,
                    "Offset ledger frontier agrees with current commit again"
                );
            }
            return;
        };
        counter!(
            "ingestion_consumer_ledger_mismatch_total",
            "topic" => mismatch.topic_partition.topic.clone(),
            "partition" => mismatch.topic_partition.partition.to_string(),
            "direction" => mismatch.direction()
        )
        .increment(1);
        // A new generation is a new assignment, so its first disagreement
        // logs again.
        let entered = mismatched.insert(topic_partition.clone(), settlement.generation)
            != Some(settlement.generation);
        if entered {
            warn!(
                topic = %mismatch.topic_partition.topic,
                partition = mismatch.topic_partition.partition,
                committed = mismatch.committed,
                frontier = ?mismatch.frontier,
                direction = mismatch.direction(),
                depth = settlement.held.offsets,
                batch_generation = stamp,
                ledger_generation = settlement.generation,
                "Offset ledger frontier differs from current commit"
            );
        }
    }
}

/// A mismatch between the current commit calculation and the ledger frontier.
#[derive(Debug, PartialEq, Eq)]
struct LedgerMismatch {
    topic_partition: TopicPartition,
    committed: i64,
    frontier: Option<Offset>,
}

impl LedgerMismatch {
    /// `"ahead"` when the ledger frontier passed the current commit,
    /// `"behind"` when it trails it.
    fn direction(&self) -> &'static str {
        match self.frontier {
            Some(frontier) if frontier.0 > self.committed => "ahead",
            _ => "behind",
        }
    }
}

/// Compare the ledger frontier with the commit the consumer calculates from
/// the batch's offset span. The frontier is next-to-read and the commit path
/// submits `span.last + 1`, so the two agree when equal.
fn frontier_mismatch(
    topic_partition: &TopicPartition,
    frontier: Option<Offset>,
    span: &OffsetSpan,
) -> Option<LedgerMismatch> {
    let committed = span.last + 1;
    if frontier == Some(Offset(committed)) {
        return None;
    }
    Some(LedgerMismatch {
        topic_partition: topic_partition.clone(),
        committed,
        frontier,
    })
}

#[derive(Debug, Clone, Copy)]
enum RejectedSlice {
    /// Exactly the offsets the charge submitted to the ledger.
    Charged {
        first: Option<i64>,
        last: Option<i64>,
        offsets: usize,
    },
    /// The batch's delivered span for the partition, not the settled slice.
    /// A generation change mid-batch drops the old generation's charges but
    /// leaves the span whole, so the span can cover offsets the settlement
    /// never submitted. The settled offsets are an iterator the happy path
    /// does not collect, so the span is the closest description available.
    /// The error names the offending offset.
    Settled { first: i64, last: i64 },
}

impl RejectedSlice {
    fn charged(charges: &[(Offset, Charge)]) -> Self {
        Self::Charged {
            first: charges.first().map(|(offset, _)| offset.0),
            last: charges.last().map(|(offset, _)| offset.0),
            offsets: charges.len(),
        }
    }

    fn settled(span: &OffsetSpan) -> Self {
        Self::Settled {
            first: span.first,
            last: span.last,
        }
    }
}

/// Count one charge or settlement the ledger rejected. A stale slice is
/// expected around a rebalance; a violation is a bug in the accounting.
/// Callers must build `slice` inside their error arm so the happy path pays
/// nothing for it.
fn count_rejection(
    stage: &'static str,
    topic_partition: &TopicPartition,
    rejection: Rejection,
    slice: RejectedSlice,
) {
    match rejection {
        Rejection::Stale { .. } => {
            counter!("ingestion_consumer_ledger_stale_slices_total", "stage" => stage).increment(1);
        }
        Rejection::Violation {
            error,
            stamp,
            generation,
            held,
        } => {
            counter!(
                "ingestion_consumer_ledger_errors_total",
                "stage" => stage,
                "kind" => error.kind()
            )
            .increment(1);
            // A tracing field name is fixed at the call site, so each variant
            // needs its own `warn!`.
            match slice {
                RejectedSlice::Charged {
                    first,
                    last,
                    offsets,
                } => warn!(
                    stage,
                    topic = %topic_partition.topic,
                    partition = topic_partition.partition,
                    error = %error,
                    kind = error.kind(),
                    batch_generation = stamp,
                    ledger_generation = generation,
                    depth = held.offsets,
                    slice_first = ?first,
                    slice_last = ?last,
                    slice_offsets = offsets,
                    "Offset ledger rejected a slice and reset its partition"
                ),
                RejectedSlice::Settled { first, last } => warn!(
                    stage,
                    topic = %topic_partition.topic,
                    partition = topic_partition.partition,
                    error = %error,
                    kind = error.kind(),
                    batch_generation = stamp,
                    ledger_generation = generation,
                    depth = held.offsets,
                    batch_first = first,
                    batch_last = last,
                    "Offset ledger rejected a slice and reset its partition"
                ),
            }
        }
    }
}

/// Publish what a partition's window holds: its uncommitted offsets and the
/// events and bytes they carry.
pub(crate) fn set_held_gauges(topic: &str, partition: i32, held: Held) {
    let topic: Arc<str> = Arc::from(topic);
    let partition: Arc<str> = Arc::from(partition.to_string());
    gauge!(
        "ingestion_consumer_ledger_uncommitted_offsets",
        "topic" => topic.clone(),
        "partition" => partition.clone()
    )
    .set(held.offsets as f64);
    gauge!(
        "ingestion_consumer_ledger_uncommitted_events",
        "topic" => topic.clone(),
        "partition" => partition.clone()
    )
    .set(held.charge.events as f64);
    gauge!(
        "ingestion_consumer_ledger_uncommitted_bytes",
        "topic" => topic,
        "partition" => partition
    )
    .set(held.charge.bytes as f64);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn span(first: i64, last: i64) -> OffsetSpan {
        OffsetSpan { first, last }
    }

    fn tp(topic: &str, partition: i32) -> TopicPartition {
        TopicPartition::new(topic, partition)
    }

    fn shadow() -> (Arc<TopicOffsetLedger>, LedgerShadow) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        (Arc::clone(&ledger), LedgerShadow::new(Some(ledger)))
    }

    fn charges(offsets: &[i64]) -> Vec<(Offset, Charge)> {
        offsets
            .iter()
            .map(|&offset| (Offset(offset), Charge::ZERO))
            .collect()
    }

    #[test]
    fn settle_drains_live_partitions_and_skips_stale_batches() {
        let (ledger, shadow) = shadow();
        let reassigned = tp("events", 0);
        let live = tp("events", 1);
        shadow.charge(&reassigned, 0, &charges(&[10]));
        shadow.charge(&live, 0, &charges(&[20]));

        // Partition 0 is revoked and reassigned while the batch is in flight.
        ledger.forget_partitions([("events", 0)]);
        shadow.charge(&reassigned, 1, &charges(&[10]));

        assert!(
            shadow
                .settle(&reassigned, 0, [Offset(10)], &span(10, 10))
                .is_none(),
            "the stale batch settles nothing against the new ledger"
        );
        let settlement = shadow
            .settle(&live, 0, [Offset(20)], &span(20, 20))
            .expect("the live batch settles");
        assert_eq!(settlement.frontier, Some(Offset(21)));
        shadow.drain(&live);

        assert_eq!(ledger.held(&reassigned).offsets, 1);
        assert_eq!(ledger.held(&live).offsets, 0, "the live batch drains");
    }

    #[test]
    fn a_partition_with_an_incomplete_prefix_holds_its_offsets() {
        let (ledger, shadow) = shadow();
        let held = tp("events", 0);
        shadow.charge(&held, 0, &charges(&[10, 11]));

        let settlement = shadow
            .settle(&held, 0, [Offset(11)], &span(11, 11))
            .expect("the batch settles");
        assert_eq!(settlement.frontier, None);
        shadow.drain(&held);

        assert_eq!(ledger.held(&held).offsets, 2);
    }

    #[test]
    fn a_shadow_without_a_ledger_does_nothing() {
        let shadow = LedgerShadow::new(None);
        let p0 = tp("events", 0);
        shadow.charge(&p0, 0, &charges(&[10]));
        assert!(shadow.settle(&p0, 0, [Offset(10)], &span(10, 10)).is_none());
        shadow.drain(&p0);

        assert_eq!(shadow.generations_version(), 0);
        assert_eq!(shadow.generation(&p0), 0);
    }

    #[test]
    fn a_mismatch_is_tracked_from_its_first_batch_until_the_frontier_agrees() {
        let (_, shadow) = shadow();
        let p0 = tp("events", 0);
        shadow.charge(&p0, 0, &charges(&[10, 11]));

        // Only offset 11 completes: the frontier stays behind the commit.
        shadow.settle(&p0, 0, [Offset(11)], &span(10, 11));
        assert_eq!(shadow.mismatched.lock().unwrap().get(&p0), Some(&0));

        // Offset 10 completes and the frontier catches up.
        shadow.settle(&p0, 0, [Offset(10)], &span(10, 11));
        assert!(shadow.mismatched.lock().unwrap().is_empty());
    }

    #[test]
    fn frontier_matching_the_commit_is_not_a_mismatch() {
        assert!(frontier_mismatch(&tp("events", 0), Some(Offset(12)), &span(11, 11)).is_none());
    }

    #[test]
    fn a_trailing_or_absent_frontier_is_behind() {
        let mismatch = frontier_mismatch(&tp("events", 0), Some(Offset(11)), &span(11, 11))
            .expect("frontier below the commit");
        assert_eq!(mismatch.committed, 12);
        assert_eq!(mismatch.direction(), "behind");

        let mismatch =
            frontier_mismatch(&tp("events", 0), None, &span(11, 11)).expect("no frontier yet");
        assert_eq!(mismatch.direction(), "behind");
    }

    #[test]
    fn a_frontier_past_the_commit_is_ahead() {
        let mismatch = frontier_mismatch(&tp("events", 0), Some(Offset(13)), &span(11, 11))
            .expect("frontier above the commit");
        assert_eq!(mismatch.direction(), "ahead");
    }

    #[test]
    fn a_violating_charge_resets_the_partition_and_the_shadow_carries_on() {
        let (ledger, shadow) = shadow();
        let p0 = tp("events", 0);
        shadow.charge(&p0, 0, &charges(&[10]));

        // The same offset delivered twice under one generation is a contract
        // violation, not a rebalance: the ledger resets the partition.
        shadow.charge(&p0, 0, &charges(&[10]));
        assert_eq!(ledger.held(&p0).offsets, 0, "the window is discarded");
        assert_eq!(ledger.generation(&p0), 1);

        // The batch in flight from before the reset settles as stale, and the
        // next delivery under the new generation founds a fresh ledger.
        shadow.settle(&p0, 0, [Offset(10)], &span(10, 10));
        shadow.charge(&p0, 1, &charges(&[11]));
        assert_eq!(ledger.held(&p0).offsets, 1);
        shadow.settle(&p0, 1, [Offset(11)], &span(11, 11));
        shadow.drain(&p0);
        assert_eq!(
            ledger.held(&p0).offsets,
            0,
            "the fresh ledger settles and drains"
        );
    }

    #[test]
    fn a_violating_settlement_resets_the_partition_and_the_shadow_carries_on() {
        let (ledger, shadow) = shadow();
        let p0 = tp("events", 0);
        shadow.charge(&p0, 0, &charges(&[10]));

        // Settling an offset the ledger never charged resets the partition.
        shadow.settle(&p0, 0, [Offset(15)], &span(15, 15));
        assert_eq!(ledger.held(&p0).offsets, 0, "the window is discarded");
        assert_eq!(ledger.generation(&p0), 1);

        shadow.charge(&p0, 1, &charges(&[11]));
        shadow.settle(&p0, 1, [Offset(11)], &span(11, 11));
        shadow.drain(&p0);
        assert_eq!(
            ledger.held(&p0).offsets,
            0,
            "the fresh ledger settles and drains"
        );
    }
}
