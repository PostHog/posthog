//! Shadow-mode verification of the offset ledger: compares the frontier the
//! ledger reaches with the commit the consumer calculates today, and carries
//! the ledger's metric vocabulary.

use std::collections::HashMap;

use common_kafka_consumer::{
    EpochOffsets, Offset, Settlement, StaleReason, TopicOffsetLedger, TopicPartition,
};
use metrics::{counter, gauge};
use tracing::warn;

use crate::order_sentinel::OffsetSpan;

/// Settle each partition's completed offsets against its ledger and report
/// every disagreement between the ledger frontier and the commit calculated
/// from the batch's offset span. Returns the settled partitions with their
/// frontiers; the caller drains each with `take_frontier` once its frontier
/// is recorded.
pub(crate) fn settle_ledger<'a>(
    ledger: &TopicOffsetLedger,
    ledger_offsets: &'a HashMap<TopicPartition, EpochOffsets>,
    offset_spans: &HashMap<TopicPartition, OffsetSpan>,
) -> Vec<(&'a TopicPartition, Option<Offset>)> {
    let mut settled = Vec::with_capacity(ledger_offsets.len());
    for (topic_partition, batch) in ledger_offsets {
        let settlement = match ledger.complete(topic_partition, batch) {
            Ok(settlement) => settlement,
            Err(reason) => {
                count_stale_slice("complete", reason);
                continue;
            }
        };
        let span = offset_spans
            .get(topic_partition)
            .expect("completed offsets must have a commit span");
        if let Some(mismatch) = frontier_mismatch(topic_partition, settlement.frontier, span) {
            report_mismatch(&mismatch, &settlement, batch.epoch);
        }
        settled.push((topic_partition, settlement.frontier));
    }
    settled
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

/// Report one frontier/commit disagreement, with the settlement context a
/// triage needs.
fn report_mismatch(mismatch: &LedgerMismatch, settlement: &Settlement, batch_epoch: u64) {
    counter!(
        "ingestion_consumer_ledger_mismatch_total",
        "topic" => mismatch.topic_partition.0.clone(),
        "partition" => mismatch.topic_partition.1.to_string(),
        "direction" => mismatch.direction()
    )
    .increment(1);
    warn!(
        topic = %mismatch.topic_partition.0,
        partition = mismatch.topic_partition.1,
        committed = mismatch.committed,
        frontier = ?mismatch.frontier,
        direction = mismatch.direction(),
        depth = settlement.depth,
        batch_epoch,
        ledger_epoch = settlement.ledger_epoch,
        "Offset ledger frontier differs from current commit"
    );
}

/// Count one charge or completion the ledger dropped as stale.
pub(crate) fn count_stale_slice(stage: &'static str, reason: StaleReason) {
    let reason = match reason {
        StaleReason::NoLedger => "no_ledger",
        StaleReason::StaleEpoch => "stale_epoch",
    };
    counter!(
        "ingestion_consumer_ledger_stale_slices_total",
        "stage" => stage,
        "reason" => reason
    )
    .increment(1);
}

/// Publish a partition's uncommitted-offset depth.
pub(crate) fn set_depth_gauge(topic: &str, partition: i32, depth: usize) {
    gauge!(
        "ingestion_consumer_ledger_uncommitted_offsets",
        "topic" => topic.to_string(),
        "partition" => partition.to_string()
    )
    .set(depth as f64);
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Arc;

    use common_kafka_consumer::Charge;

    use super::*;

    fn span(last: i64) -> OffsetSpan {
        OffsetSpan { first: last, last }
    }

    fn tp(topic: &str, partition: i32) -> TopicPartition {
        (topic.to_string(), partition)
    }

    #[test]
    fn settle_skips_stale_batches_and_returns_live_frontiers() {
        let epoch = Arc::new(AtomicU64::new(1));
        let ledger = TopicOffsetLedger::new(Arc::clone(&epoch));
        let reassigned = tp("events", 0);
        let live = tp("events", 1);
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger
            .charge("events", 1, 1, [(Offset(20), Charge::ZERO)])
            .unwrap();

        // Partition 0 is revoked and reassigned while the batch is in flight.
        ledger.forget_partitions([("events", 0)]);
        epoch.store(2, Ordering::Relaxed);
        ledger
            .charge("events", 0, 2, [(Offset(10), Charge::ZERO)])
            .unwrap();

        let ledger_offsets = HashMap::from([
            (
                reassigned.clone(),
                EpochOffsets {
                    epoch: 1,
                    offsets: vec![Offset(10)],
                },
            ),
            (
                live.clone(),
                EpochOffsets {
                    epoch: 1,
                    offsets: vec![Offset(20)],
                },
            ),
        ]);
        let offset_spans =
            HashMap::from([(reassigned.clone(), span(10)), (live.clone(), span(20))]);

        let settled = settle_ledger(&ledger, &ledger_offsets, &offset_spans);
        assert_eq!(
            settled,
            vec![(&live, Some(Offset(21)))],
            "only the live batch settles; the caller must not drain the reassigned partition"
        );
        assert_eq!(
            ledger.depth(&reassigned),
            1,
            "the stale batch settles nothing against the new ledger"
        );
    }

    #[test]
    fn a_partition_with_an_incomplete_prefix_settles_without_a_frontier() {
        let epoch = Arc::new(AtomicU64::new(1));
        let ledger = TopicOffsetLedger::new(Arc::clone(&epoch));
        let held = tp("events", 0);
        ledger
            .charge(
                "events",
                0,
                1,
                [(Offset(10), Charge::ZERO), (Offset(11), Charge::ZERO)],
            )
            .unwrap();

        let ledger_offsets = HashMap::from([(
            held.clone(),
            EpochOffsets {
                epoch: 1,
                offsets: vec![Offset(11)],
            },
        )]);
        let offset_spans = HashMap::from([(held.clone(), span(11))]);

        let settled = settle_ledger(&ledger, &ledger_offsets, &offset_spans);
        assert_eq!(settled, vec![(&held, None)]);
    }

    #[test]
    fn frontier_matching_the_commit_is_not_a_mismatch() {
        assert!(frontier_mismatch(&tp("events", 0), Some(Offset(12)), &span(11)).is_none());
    }

    #[test]
    fn a_trailing_or_absent_frontier_is_behind() {
        let mismatch = frontier_mismatch(&tp("events", 0), Some(Offset(11)), &span(11))
            .expect("frontier below the commit");
        assert_eq!(mismatch.committed, 12);
        assert_eq!(mismatch.direction(), "behind");

        let mismatch =
            frontier_mismatch(&tp("events", 0), None, &span(11)).expect("no frontier yet");
        assert_eq!(mismatch.direction(), "behind");
    }

    #[test]
    fn a_frontier_past_the_commit_is_ahead() {
        let mismatch = frontier_mismatch(&tp("events", 0), Some(Offset(13)), &span(11))
            .expect("frontier above the commit");
        assert_eq!(mismatch.direction(), "ahead");
    }
}
