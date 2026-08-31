use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use crate::charge::Charge;
use crate::partition_offset_ledger::PartitionOffsetLedger;
use crate::types::Offset;

pub type TopicPartition = (String, i32);

/// One batch's ledger offsets for one partition, stamped with the assignment
/// epoch that was current when they were buffered.
#[derive(Debug)]
pub struct EpochOffsets {
    pub epoch: u64,
    pub offsets: Vec<Offset>,
}

/// Why a charge or completion did not reach any ledger.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StaleReason {
    /// The partition has no ledger: it was revoked after the work was
    /// buffered, and no current-epoch delivery founded a new one.
    NoLedger,
    /// The partition's ledger belongs to a newer assignment than the work.
    StaleEpoch,
}

/// One batch's settled view of its partition ledger: the frontier after its
/// offsets landed, plus the context a mismatch report needs.
#[derive(Debug)]
pub struct Settlement {
    /// Next-to-read frontier, `None` while the first offset of the window is
    /// still incomplete.
    pub frontier: Option<Offset>,
    /// Offsets still held by the window after the completion.
    pub depth: usize,
    pub ledger_epoch: u64,
}

/// One [`PartitionOffsetLedger`] per assigned partition, each stamped with the
/// assignment epoch it was founded under, so charges and completions that
/// predate a partition's current assignment are dropped instead of
/// corrupting it.
pub struct TopicOffsetLedger {
    /// Bumped by the owner on every assign; work is stamped with it as it is
    /// buffered.
    assignment_epoch: Arc<AtomicU64>,
    partitions: Mutex<HashMap<TopicPartition, PartitionOffsetLedger>>,
}

impl TopicOffsetLedger {
    pub fn new(assignment_epoch: Arc<AtomicU64>) -> Self {
        Self {
            assignment_epoch,
            partitions: Mutex::new(HashMap::new()),
        }
    }

    /// The current assignment epoch, for stamping work as it is buffered.
    pub fn epoch(&self) -> u64 {
        self.assignment_epoch.load(Ordering::Relaxed)
    }

    /// Record one slice of delivered offsets on the partition's ledger,
    /// founding the ledger when the slice is the assignment's first delivery.
    /// Returns the partition's depth after the charge, or the reason the
    /// slice was dropped.
    pub fn charge(
        &self,
        topic: &str,
        partition: i32,
        epoch: u64,
        offset_charges: impl IntoIterator<Item = (Offset, Charge)>,
    ) -> Result<usize, StaleReason> {
        let mut partitions = self.partitions.lock().unwrap();
        let entry = match partitions.entry((topic.to_string(), partition)) {
            Entry::Occupied(occupied) => {
                let entry = occupied.into_mut();
                // The ledger belongs to a newer assignment than the slice:
                // Kafka redelivers the slice's offsets under it. A slice
                // that merely spans an unrelated epoch bump has
                // epoch >= entry.epoch and charges normally.
                if epoch < entry.epoch() {
                    return Err(StaleReason::StaleEpoch);
                }
                entry
            }
            Entry::Vacant(vacant) => {
                // No ledger means the partition was revoked after the slice
                // was buffered; only a slice from the current assignment may
                // found the new ledger.
                if epoch != self.epoch() {
                    return Err(StaleReason::NoLedger);
                }
                vacant.insert(PartitionOffsetLedger::new(epoch))
            }
        };
        entry.charge(offset_charges);
        Ok(entry.len())
    }

    /// Mark one batch's offsets complete on the partition's ledger and report
    /// the frontier that results; the window holds the offsets until
    /// `take_frontier` drains them. Settles nothing when the batch's offsets
    /// no longer belong to the partition's current ledger; Kafka redelivers
    /// them under the current assignment.
    pub fn complete(
        &self,
        topic_partition: &TopicPartition,
        batch: &EpochOffsets,
    ) -> Result<Settlement, StaleReason> {
        let mut partitions = self.partitions.lock().unwrap();
        // A rebalance dropped this partition's ledger between delivery and
        // completion.
        let Some(entry) = partitions.get_mut(topic_partition) else {
            return Err(StaleReason::NoLedger);
        };
        // The ledger belongs to a newer assignment than the batch: the
        // batch's offsets were already dropped with the old ledger.
        if batch.epoch < entry.epoch() {
            return Err(StaleReason::StaleEpoch);
        }
        entry.complete(&batch.offsets);
        Ok(Settlement {
            frontier: entry.frontier(),
            depth: entry.len(),
            ledger_epoch: entry.epoch(),
        })
    }

    /// Drain the completed prefix and return the frontier it reached; `None`
    /// when the partition has no ledger or nothing has completed at the front
    /// of its window.
    pub fn take_frontier(&self, topic_partition: &TopicPartition) -> Option<Offset> {
        let mut partitions = self.partitions.lock().unwrap();
        let entry = partitions.get_mut(topic_partition)?;
        entry.take_frontier().map(|taken| taken.offset)
    }

    /// Offsets the partition's window still holds; 0 without a ledger.
    pub fn depth(&self, topic_partition: &TopicPartition) -> usize {
        self.partitions
            .lock()
            .unwrap()
            .get(topic_partition)
            .map(PartitionOffsetLedger::len)
            .unwrap_or_default()
    }

    /// Drop the revoked partitions' ledgers before their redelivery is
    /// charged: a kept ledger sees redelivered offsets as duplicate delivery
    /// and panics.
    pub fn forget_partitions<'a>(&self, revoked: impl IntoIterator<Item = (&'a str, i32)>) {
        let mut partitions = self.partitions.lock().unwrap();
        for (topic, partition) in revoked {
            partitions.remove(&(topic.to_string(), partition));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn new_ledger() -> (Arc<AtomicU64>, TopicOffsetLedger) {
        let epoch = Arc::new(AtomicU64::new(1));
        let ledger = TopicOffsetLedger::new(Arc::clone(&epoch));
        (epoch, ledger)
    }

    fn batch(epoch: u64, offsets: Vec<Offset>) -> EpochOffsets {
        EpochOffsets { epoch, offsets }
    }

    fn tp(topic: &str, partition: i32) -> TopicPartition {
        (topic.to_string(), partition)
    }

    #[test]
    fn a_completed_batch_reports_its_frontier_and_drains() {
        let (_, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger
            .charge("events", 0, 1, [(Offset(11), Charge::ZERO)])
            .unwrap();

        let settlement = ledger
            .complete(&tp("events", 0), &batch(1, vec![Offset(10), Offset(11)]))
            .expect("live ledger settles");
        assert_eq!(settlement.frontier, Some(Offset(12)));

        assert_eq!(ledger.take_frontier(&tp("events", 0)), Some(Offset(12)));
        assert_eq!(ledger.depth(&tp("events", 0)), 0);
    }

    #[test]
    fn revoked_partitions_drop_their_ledger() {
        let (_, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger.forget_partitions([("events", 0)]);

        assert_eq!(ledger.depth(&tp("events", 0)), 0);
    }

    #[test]
    fn an_incomplete_prefix_reports_no_frontier_and_holds_offsets() {
        let (_, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger
            .charge("events", 0, 1, [(Offset(11), Charge::ZERO)])
            .unwrap();

        let settlement = ledger
            .complete(&tp("events", 0), &batch(1, vec![Offset(11)]))
            .expect("live ledger settles");
        assert_eq!(settlement.frontier, None);
        assert_eq!(settlement.depth, 2);
        assert_eq!(ledger.take_frontier(&tp("events", 0)), None);
        assert_eq!(ledger.depth(&tp("events", 0)), 2);

        // The late completion arrives with the next batch and the held
        // offsets drain.
        let settlement = ledger
            .complete(&tp("events", 0), &batch(1, vec![Offset(10)]))
            .expect("live ledger settles");
        assert_eq!(settlement.frontier, Some(Offset(12)));
        assert_eq!(ledger.take_frontier(&tp("events", 0)), Some(Offset(12)));
        assert_eq!(ledger.depth(&tp("events", 0)), 0);
    }

    #[test]
    fn a_batch_spanning_partitions_settles_each_independently() {
        let (_, ledger) = new_ledger();
        ledger
            .charge(
                "events",
                0,
                1,
                [(Offset(10), Charge::ZERO), (Offset(11), Charge::ZERO)],
            )
            .unwrap();
        ledger
            .charge(
                "events",
                1,
                1,
                [(Offset(20), Charge::ZERO), (Offset(21), Charge::ZERO)],
            )
            .unwrap();

        let settled = ledger
            .complete(&tp("events", 0), &batch(1, vec![Offset(10), Offset(11)]))
            .expect("live ledger settles");
        assert_eq!(settled.frontier, Some(Offset(12)));
        let held = ledger
            .complete(&tp("events", 1), &batch(1, vec![Offset(21)]))
            .expect("live ledger settles");
        assert_eq!(held.frontier, None);

        ledger.take_frontier(&tp("events", 0));
        ledger.take_frontier(&tp("events", 1));
        assert_eq!(
            ledger.depth(&tp("events", 0)),
            0,
            "the settled partition drains"
        );
        assert_eq!(
            ledger.depth(&tp("events", 1)),
            2,
            "the held partition keeps its offsets"
        );
    }

    #[test]
    fn completions_for_a_forgotten_partition_are_skipped() {
        let (_, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger.forget_partitions([("events", 0)]);

        assert_eq!(
            ledger
                .complete(&tp("events", 0), &batch(1, vec![Offset(10)]))
                .unwrap_err(),
            StaleReason::NoLedger
        );
    }

    #[test]
    fn partitions_are_keyed_by_topic_and_partition() {
        let (_, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger
            .charge("overflow", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();

        ledger
            .complete(&tp("events", 0), &batch(1, vec![Offset(10)]))
            .expect("live ledger settles");
        ledger.take_frontier(&tp("events", 0));

        assert_eq!(ledger.depth(&tp("events", 0)), 0);
        assert_eq!(ledger.depth(&tp("overflow", 0)), 1);
    }

    #[test]
    fn stale_completions_from_a_previous_assignment_are_dropped() {
        let (epoch, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();

        // The partition is revoked and reassigned to this consumer while the
        // batch is still in flight; the redelivery recharges the same offset.
        ledger.forget_partitions([("events", 0)]);
        epoch.store(2, Ordering::Relaxed);
        ledger
            .charge("events", 0, 2, [(Offset(10), Charge::ZERO)])
            .unwrap();

        assert_eq!(
            ledger
                .complete(&tp("events", 0), &batch(1, vec![Offset(10)]))
                .unwrap_err(),
            StaleReason::StaleEpoch
        );
        assert_eq!(
            ledger.depth(&tp("events", 0)),
            1,
            "the redelivered offset stays uncompleted"
        );

        // The redelivery's own completion settles the new assignment's ledger.
        ledger
            .complete(&tp("events", 0), &batch(2, vec![Offset(10)]))
            .expect("current-epoch batch settles");
        ledger.take_frontier(&tp("events", 0));
        assert_eq!(ledger.depth(&tp("events", 0)), 0);
    }

    #[test]
    fn an_epoch_spanning_batch_drops_only_the_reassigned_partition() {
        let (epoch, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger
            .charge("events", 1, 1, [(Offset(20), Charge::ZERO)])
            .unwrap();

        // Only partition 0 is revoked and reassigned; the epoch bump is
        // global.
        ledger.forget_partitions([("events", 0)]);
        epoch.store(2, Ordering::Relaxed);
        ledger
            .charge("events", 0, 2, [(Offset(10), Charge::ZERO)])
            .unwrap();

        assert_eq!(
            ledger
                .complete(&tp("events", 0), &batch(1, vec![Offset(10)]))
                .unwrap_err(),
            StaleReason::StaleEpoch
        );
        ledger
            .complete(&tp("events", 1), &batch(1, vec![Offset(20)]))
            .expect("untouched partition settles");
        ledger.take_frontier(&tp("events", 1));

        assert_eq!(
            ledger.depth(&tp("events", 0)),
            1,
            "the reassigned partition ignores the stale completion"
        );
        assert_eq!(
            ledger.depth(&tp("events", 1)),
            0,
            "the untouched partition completes and drains"
        );
    }

    #[test]
    fn slices_spanning_an_unrelated_epoch_bump_still_charge() {
        let (epoch, ledger) = new_ledger();
        ledger
            .charge("events", 1, 1, [(Offset(20), Charge::ZERO)])
            .unwrap();

        // Another partition's reassignment bumps the epoch; this partition's
        // ledger survives and its old-stamped slice must not be lost.
        epoch.store(2, Ordering::Relaxed);
        ledger
            .charge("events", 1, 1, [(Offset(21), Charge::ZERO)])
            .unwrap();
        assert_eq!(ledger.depth(&tp("events", 1)), 2);

        ledger
            .complete(&tp("events", 1), &batch(1, vec![Offset(20), Offset(21)]))
            .expect("surviving ledger settles");
        ledger.take_frontier(&tp("events", 1));
        assert_eq!(ledger.depth(&tp("events", 1)), 0, "no message is lost");
    }

    #[test]
    fn a_partition_lost_for_an_epoch_returns_under_a_later_epoch() {
        let (epoch, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();

        // The partition leaves for another consumer, then returns two
        // assignments later; the in-flight batch settles in between.
        ledger.forget_partitions([("events", 0)]);
        epoch.store(3, Ordering::Relaxed);

        assert_eq!(
            ledger
                .complete(&tp("events", 0), &batch(1, vec![Offset(10)]))
                .unwrap_err(),
            StaleReason::NoLedger
        );
        assert_eq!(
            ledger.depth(&tp("events", 0)),
            0,
            "no ledger, nothing lands"
        );

        ledger
            .charge("events", 0, 3, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger
            .complete(&tp("events", 0), &batch(3, vec![Offset(10)]))
            .expect("the new assignment settles");
        ledger.take_frontier(&tp("events", 0));
        assert_eq!(ledger.depth(&tp("events", 0)), 0);
    }

    #[test]
    fn batches_from_older_epochs_settle_against_a_surviving_ledger() {
        let (epoch, ledger) = new_ledger();
        ledger
            .charge("events", 1, 1, [(Offset(20), Charge::ZERO)])
            .unwrap();
        epoch.store(2, Ordering::Relaxed);
        ledger
            .charge("events", 1, 2, [(Offset(21), Charge::ZERO)])
            .unwrap();
        epoch.store(4, Ordering::Relaxed);

        // Both in-flight batches predate the current epoch; the partition was
        // never revoked, so both must land.
        ledger
            .complete(&tp("events", 1), &batch(1, vec![Offset(20)]))
            .expect("older batch settles");
        ledger.take_frontier(&tp("events", 1));
        ledger
            .complete(&tp("events", 1), &batch(2, vec![Offset(21)]))
            .expect("older batch settles");
        ledger.take_frontier(&tp("events", 1));
        assert_eq!(ledger.depth(&tp("events", 1)), 0, "no message is lost");
    }

    #[test]
    fn slices_from_every_older_epoch_cannot_refound_a_dropped_ledger() {
        let (epoch, ledger) = new_ledger();
        ledger
            .charge("events", 0, 1, [(Offset(10), Charge::ZERO)])
            .unwrap();
        ledger.forget_partitions([("events", 0)]);
        epoch.store(3, Ordering::Relaxed);

        assert_eq!(
            ledger.charge("events", 0, 1, [(Offset(10), Charge::ZERO)]),
            Err(StaleReason::NoLedger)
        );
        assert_eq!(
            ledger.charge("events", 0, 2, [(Offset(10), Charge::ZERO)]),
            Err(StaleReason::NoLedger)
        );
        assert_eq!(ledger.depth(&tp("events", 0)), 0);

        assert_eq!(
            ledger.charge("events", 0, 3, [(Offset(10), Charge::ZERO)]),
            Ok(1)
        );
    }

    #[test]
    fn charges_buffered_before_a_rebalance_are_dropped() {
        let (epoch, ledger) = new_ledger();
        epoch.store(2, Ordering::Relaxed);

        assert_eq!(
            ledger.charge("events", 0, 1, [(Offset(10), Charge::ZERO)]),
            Err(StaleReason::NoLedger)
        );
        assert_eq!(ledger.depth(&tp("events", 0)), 0);
    }

    #[test]
    fn a_stale_slice_against_a_surviving_newer_ledger_is_dropped() {
        let (epoch, ledger) = new_ledger();
        ledger.forget_partitions([("events", 0)]);
        epoch.store(2, Ordering::Relaxed);
        ledger
            .charge("events", 0, 2, [(Offset(10), Charge::ZERO)])
            .unwrap();

        assert_eq!(
            ledger.charge("events", 0, 1, [(Offset(10), Charge::ZERO)]),
            Err(StaleReason::StaleEpoch)
        );
        assert_eq!(ledger.depth(&tp("events", 0)), 1);
    }
}
