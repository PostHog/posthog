//! The consumer's offset ledger driver: charges every delivered message to
//! its partition's ledger, settles what the workers accepted, and carries the
//! ledger's metric vocabulary. The commit path takes its offsets from here.

use std::sync::Arc;

use common_kafka_consumer::{
    Charge, Held, Offset, Rejection, Settlement, TopicOffsetLedger, TopicPartition,
};
use metrics::{counter, gauge};
use tracing::warn;

/// Drives the per-partition offset ledger the commit path reads its frontiers
/// from, and reports what each partition's window holds.
pub(crate) struct CommitLedger {
    ledger: Arc<TopicOffsetLedger>,
}

impl CommitLedger {
    pub(crate) fn new(ledger: Arc<TopicOffsetLedger>) -> Self {
        Self { ledger }
    }

    /// See [`TopicOffsetLedger::generations_version`].
    pub(crate) fn generations_version(&self) -> u64 {
        self.ledger.generations_version()
    }

    /// See [`TopicOffsetLedger::generation`].
    pub(crate) fn generation(&self, topic_partition: &TopicPartition) -> u64 {
        self.ledger.generation(topic_partition)
    }

    /// Charge one batch's slice of a partition to its ledger and publish what
    /// the partition's window holds.
    pub(crate) fn charge(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        charges: &[(Offset, Charge)],
    ) {
        match self
            .ledger
            .charge(topic_partition, stamp, charges.iter().copied())
        {
            Ok(held) => set_held_gauges(&topic_partition.topic, topic_partition.partition, held),
            Err(rejection) => count_rejection("charge", topic_partition, rejection),
        }
    }

    /// Settle one batch's slice of a partition: complete its offsets and
    /// report the frontier the partition reaches. Returns the settlement, or
    /// `None` when the ledger rejected the slice. The window holds the offsets
    /// until `drain`.
    pub(crate) fn settle(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Option<Settlement> {
        match self.ledger.settle(topic_partition, stamp, offsets) {
            Ok(settlement) => Some(settlement),
            Err(rejection) => {
                count_rejection("settle", topic_partition, rejection);
                None
            }
        }
    }

    /// Drain a settled partition's completed prefix and publish what its
    /// window still holds.
    pub(crate) fn drain(&self, topic_partition: &TopicPartition) {
        self.ledger.take_frontier(topic_partition);
        set_held_gauges(
            &topic_partition.topic,
            topic_partition.partition,
            self.ledger.held(topic_partition),
        );
    }
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

    fn tp(topic: &str, partition: i32) -> TopicPartition {
        TopicPartition::new(topic, partition)
    }

    fn driver() -> (Arc<TopicOffsetLedger>, CommitLedger) {
        let ledger = Arc::new(TopicOffsetLedger::new());
        (Arc::clone(&ledger), CommitLedger::new(ledger))
    }

    fn charges(offsets: &[i64]) -> Vec<(Offset, Charge)> {
        offsets
            .iter()
            .map(|&offset| (Offset(offset), Charge::ZERO))
            .collect()
    }

    #[test]
    fn settle_drains_live_partitions_and_skips_stale_batches() {
        let (ledger, driver) = driver();
        let reassigned = tp("events", 0);
        let live = tp("events", 1);
        driver.charge(&reassigned, 0, &charges(&[10]));
        driver.charge(&live, 0, &charges(&[20]));

        // Partition 0 is revoked and reassigned while the batch is in flight.
        ledger.forget_partitions([("events", 0)]);
        driver.charge(&reassigned, 1, &charges(&[10]));

        assert!(
            driver.settle(&reassigned, 0, [Offset(10)]).is_none(),
            "the stale batch settles nothing against the new ledger"
        );
        let settlement = driver
            .settle(&live, 0, [Offset(20)])
            .expect("the live batch settles");
        assert_eq!(settlement.frontier, Some(Offset(21)));
        driver.drain(&live);

        assert_eq!(ledger.held(&reassigned).offsets, 1);
        assert_eq!(ledger.held(&live).offsets, 0, "the live batch drains");
    }

    #[test]
    fn a_partition_with_an_incomplete_prefix_holds_its_offsets() {
        let (ledger, driver) = driver();
        let held = tp("events", 0);
        driver.charge(&held, 0, &charges(&[10, 11]));

        let settlement = driver
            .settle(&held, 0, [Offset(11)])
            .expect("the batch settles");
        assert_eq!(settlement.frontier, None);
        driver.drain(&held);

        assert_eq!(ledger.held(&held).offsets, 2);
    }

    #[test]
    fn a_violating_charge_resets_the_partition_and_the_driver_carries_on() {
        let (ledger, driver) = driver();
        let p0 = tp("events", 0);
        driver.charge(&p0, 0, &charges(&[10]));

        // The same offset delivered twice under one generation is a contract
        // violation, not a rebalance: the ledger resets the partition.
        driver.charge(&p0, 0, &charges(&[10]));
        assert_eq!(ledger.held(&p0).offsets, 0, "the window is discarded");
        assert_eq!(ledger.generation(&p0), 1);

        // The batch in flight from before the reset settles as stale, and the
        // next delivery under the new generation founds a fresh ledger.
        driver.settle(&p0, 0, [Offset(10)]);
        driver.charge(&p0, 1, &charges(&[11]));
        assert_eq!(ledger.held(&p0).offsets, 1);
        driver.settle(&p0, 1, [Offset(11)]);
        driver.drain(&p0);
        assert_eq!(
            ledger.held(&p0).offsets,
            0,
            "the fresh ledger settles and drains"
        );
    }

    #[test]
    fn a_violating_settlement_resets_the_partition_and_the_driver_carries_on() {
        let (ledger, driver) = driver();
        let p0 = tp("events", 0);
        driver.charge(&p0, 0, &charges(&[10]));

        // Settling an offset the ledger never charged resets the partition.
        driver.settle(&p0, 0, [Offset(15)]);
        assert_eq!(ledger.held(&p0).offsets, 0, "the window is discarded");
        assert_eq!(ledger.generation(&p0), 1);

        driver.charge(&p0, 1, &charges(&[11]));
        driver.settle(&p0, 1, [Offset(11)]);
        driver.drain(&p0);
        assert_eq!(
            ledger.held(&p0).offsets,
            0,
            "the fresh ledger settles and drains"
        );
    }
}
