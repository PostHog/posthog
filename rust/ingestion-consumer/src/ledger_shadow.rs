//! Shadow-mode verification of the offset ledger: compares the frontier the
//! ledger reaches with the commit the consumer calculates today, and carries
//! the ledger's metric vocabulary.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use common_kafka_consumer::{
    Charge, Offset, Rejection, Settlement, TopicOffsetLedger, TopicPartition,
};
use metrics::{counter, gauge};
use tracing::{info, warn};

use crate::order_sentinel::OffsetSpan;

/// Runs the offset ledger next to the current commit path without taking
/// part in commit choice. While disabled every call is a no-op, so the flag
/// is a kill switch for the whole shadow.
pub(crate) struct LedgerShadow {
    ledger: Arc<TopicOffsetLedger>,
    enabled: bool,
    /// Partitions whose frontier disagrees with the commit, by the ledger
    /// generation the disagreement was seen under. A persistent disagreement
    /// logs when it starts and when it ends, not on every batch.
    mismatched: Mutex<HashMap<TopicPartition, u64>>,
}

impl LedgerShadow {
    pub(crate) fn new(ledger: Arc<TopicOffsetLedger>, enabled: bool) -> Self {
        Self {
            ledger,
            enabled,
            mismatched: Mutex::new(HashMap::new()),
        }
    }

    /// See [`TopicOffsetLedger::generations_version`]; constant while
    /// disabled.
    pub(crate) fn generations_version(&self) -> u64 {
        if !self.enabled {
            return 0;
        }
        self.ledger.generations_version()
    }

    /// See [`TopicOffsetLedger::generation`]; 0 while disabled.
    pub(crate) fn generation(&self, topic_partition: &TopicPartition) -> u64 {
        if !self.enabled {
            return 0;
        }
        self.ledger.generation(topic_partition)
    }

    /// Charge one batch's slice of a partition to its ledger and publish the
    /// partition's depth.
    pub(crate) fn charge(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        charges: &[(Offset, Charge)],
    ) {
        if !self.enabled {
            return;
        }
        match self
            .ledger
            .charge(topic_partition, stamp, charges.iter().copied())
        {
            Ok(depth) => set_depth_gauge(&topic_partition.topic, topic_partition.partition, depth),
            Err(rejection) => count_rejection("charge", topic_partition, rejection),
        }
    }

    /// Settle one batch's slice of a partition: complete its offsets, compare
    /// the frontier with the commit the batch submits, and drain the
    /// completed prefix.
    pub(crate) fn settle(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        offsets: impl IntoIterator<Item = Offset>,
        span: &OffsetSpan,
    ) {
        if !self.enabled {
            return;
        }
        let settlement = match self.ledger.settle(topic_partition, stamp, offsets) {
            Ok(settlement) => settlement,
            Err(rejection) => {
                count_rejection("settle", topic_partition, rejection);
                return;
            }
        };
        self.observe(topic_partition, &settlement, span, stamp);
        self.ledger.take_frontier(topic_partition);
        set_depth_gauge(
            &topic_partition.topic,
            topic_partition.partition,
            self.ledger.depth(topic_partition),
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
                depth = settlement.depth,
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

/// Count one charge or settlement the ledger rejected. A stale slice is
/// expected around a rebalance; a violation is a bug in the accounting.
fn count_rejection(stage: &'static str, topic_partition: &TopicPartition, rejection: Rejection) {
    match rejection {
        Rejection::Stale { .. } => {
            counter!("ingestion_consumer_ledger_stale_slices_total", "stage" => stage).increment(1);
        }
        Rejection::Violation(error) => {
            counter!(
                "ingestion_consumer_ledger_errors_total",
                "stage" => stage,
                "kind" => error.kind()
            )
            .increment(1);
            warn!(
                stage,
                topic = %topic_partition.topic,
                partition = topic_partition.partition,
                error = %error,
                "Offset ledger rejected a slice and reset its partition"
            );
        }
    }
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
    use super::*;

    fn span(first: i64, last: i64) -> OffsetSpan {
        OffsetSpan { first, last }
    }

    fn tp(topic: &str, partition: i32) -> TopicPartition {
        TopicPartition::new(topic, partition)
    }

    fn shadow(enabled: bool) -> (Arc<TopicOffsetLedger>, LedgerShadow) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        (Arc::clone(&ledger), LedgerShadow::new(ledger, enabled))
    }

    fn charges(offsets: &[i64]) -> Vec<(Offset, Charge)> {
        offsets
            .iter()
            .map(|&offset| (Offset(offset), Charge::ZERO))
            .collect()
    }

    #[test]
    fn settle_drains_live_partitions_and_skips_stale_batches() {
        let (ledger, shadow) = shadow(true);
        let reassigned = tp("events", 0);
        let live = tp("events", 1);
        shadow.charge(&reassigned, 0, &charges(&[10]));
        shadow.charge(&live, 0, &charges(&[20]));

        // Partition 0 is revoked and reassigned while the batch is in flight.
        ledger.forget_partitions([("events", 0)]);
        shadow.charge(&reassigned, 1, &charges(&[10]));

        shadow.settle(&reassigned, 0, [Offset(10)], &span(10, 10));
        shadow.settle(&live, 0, [Offset(20)], &span(20, 20));

        assert_eq!(
            ledger.depth(&reassigned),
            1,
            "the stale batch settles nothing against the new ledger"
        );
        assert_eq!(ledger.depth(&live), 0, "the live batch settles and drains");
    }

    #[test]
    fn a_partition_with_an_incomplete_prefix_holds_its_offsets() {
        let (ledger, shadow) = shadow(true);
        let held = tp("events", 0);
        shadow.charge(&held, 0, &charges(&[10, 11]));

        shadow.settle(&held, 0, [Offset(11)], &span(11, 11));

        assert_eq!(ledger.depth(&held), 2);
    }

    #[test]
    fn a_disabled_shadow_touches_nothing() {
        let (ledger, shadow) = shadow(false);
        let p0 = tp("events", 0);
        shadow.charge(&p0, 0, &charges(&[10]));
        shadow.settle(&p0, 0, [Offset(10)], &span(10, 10));

        assert_eq!(ledger.depth(&p0), 0);
        assert_eq!(shadow.generations_version(), 0);
        assert_eq!(shadow.generation(&p0), 0);
    }

    #[test]
    fn a_mismatch_is_tracked_from_its_first_batch_until_the_frontier_agrees() {
        let (_, shadow) = shadow(true);
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
}
