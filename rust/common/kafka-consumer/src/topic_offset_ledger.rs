use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use crate::charge::Charge;
use crate::partition_offset_ledger::{LedgerError, PartitionOffsetLedger};
use crate::types::Offset;

/// A partition of a named topic, the key for everything the ledger tracks.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct TopicPartition {
    pub topic: String,
    pub partition: i32,
}

impl TopicPartition {
    pub fn new(topic: impl Into<String>, partition: i32) -> Self {
        Self {
            topic: topic.into(),
            partition,
        }
    }
}

/// Why a charge or settlement did not land on its partition's ledger.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rejection {
    /// The work predates the partition's current assignment. Kafka
    /// redelivers its offsets under the current one, so nothing is lost.
    Stale { stamp: u64, generation: u64 },
    /// The work violated the ledger's contract. The partition's window is
    /// unknown after this, so its ledger was reset to a new generation: work
    /// in flight drops as stale, and the next delivery founds a fresh ledger.
    Violation(LedgerError),
}

/// One batch's settled view of its partition ledger: the frontier after its
/// offsets landed, plus the context a mismatch report needs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Settlement {
    /// Next-to-read frontier, `None` while the first offset of the window is
    /// still incomplete.
    pub frontier: Option<Offset>,
    /// Offsets still held by the window after the completion.
    pub depth: usize,
    pub generation: u64,
}

/// One [`PartitionOffsetLedger`] per partition, each founded under a
/// per-partition generation. Forgetting a partition advances its generation and
/// replaces its ledger in one step, so charges and completions stamped with an
/// earlier generation are dropped instead of corrupting the new assignment.
///
/// Staleness is one rule: work whose stamp is below the partition's current
/// generation is stale. Generations are independent per partition, so one
/// partition's reassignment never affects another's in-flight work.
#[derive(Default)]
pub struct TopicOffsetLedger {
    partitions: Mutex<HashMap<TopicPartition, PartitionOffsetLedger>>,
    /// Version of the per-partition generation map: moves whenever any
    /// partition's generation does. A caller stamping work outside the lock
    /// reads this per message and only re-reads the partition's generation
    /// when it moved.
    generations_version: AtomicU64,
}

impl TopicOffsetLedger {
    pub fn new() -> Self {
        Self::default()
    }

    /// The partition's current generation, for stamping work as it is
    /// buffered; 0 for a partition the ledger has never seen.
    pub fn generation(&self, topic_partition: &TopicPartition) -> u64 {
        self.partitions
            .lock()
            .unwrap()
            .get(topic_partition)
            .map(PartitionOffsetLedger::generation)
            .unwrap_or_default()
    }

    /// Version of the per-partition generation map. Cheaper than
    /// `generation` and moves whenever any generation does, so a caller
    /// compares it per message and consults `generation` only on a change.
    pub fn generations_version(&self) -> u64 {
        self.generations_version.load(Ordering::Relaxed)
    }

    /// Record one slice of delivered offsets on the partition's ledger,
    /// founding the ledger when the slice is the partition's first delivery.
    /// Returns the partition's depth after the charge, or why the slice was
    /// rejected.
    pub fn charge(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        offset_charges: impl IntoIterator<Item = (Offset, Charge)>,
    ) -> Result<usize, Rejection> {
        let mut partitions = self.partitions.lock().unwrap();
        let ledger = partitions
            .entry(topic_partition.clone())
            .or_insert_with(|| PartitionOffsetLedger::new(0));
        let generation = ledger.generation();
        if stamp < generation {
            return Err(Rejection::Stale { stamp, generation });
        }
        match ledger.charge(offset_charges) {
            Ok(_) => Ok(ledger.depth()),
            Err(error) => {
                *ledger = PartitionOffsetLedger::new(generation + 1);
                self.generations_version.fetch_add(1, Ordering::Relaxed);
                Err(Rejection::Violation(error))
            }
        }
    }

    /// Settle one batch's offsets, stamped with the generation they were
    /// buffered under: mark them complete on the partition's ledger and
    /// report the frontier that results. The window holds the offsets until
    /// `take_frontier` drains them.
    pub fn settle(
        &self,
        topic_partition: &TopicPartition,
        stamp: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<Settlement, Rejection> {
        let mut partitions = self.partitions.lock().unwrap();
        let Some(ledger) = partitions.get_mut(topic_partition) else {
            // Nothing was ever charged, so the batch cannot have been either.
            return Err(Rejection::Stale {
                stamp,
                generation: 0,
            });
        };
        let generation = ledger.generation();
        if stamp < generation {
            return Err(Rejection::Stale { stamp, generation });
        }
        match ledger.complete(offsets) {
            Ok(()) => Ok(Settlement {
                frontier: ledger.frontier(),
                depth: ledger.depth(),
                generation,
            }),
            Err(error) => {
                *ledger = PartitionOffsetLedger::new(generation + 1);
                self.generations_version.fetch_add(1, Ordering::Relaxed);
                Err(Rejection::Violation(error))
            }
        }
    }

    /// Drain the completed prefix and return the frontier it reached; `None`
    /// when the partition has no ledger or nothing has completed at the front
    /// of its window.
    pub fn take_frontier(&self, topic_partition: &TopicPartition) -> Option<Offset> {
        let mut partitions = self.partitions.lock().unwrap();
        let ledger = partitions.get_mut(topic_partition)?;
        ledger.take_frontier().map(|taken| taken.offset)
    }

    /// Offsets the partition's window still holds; 0 without a ledger.
    pub fn depth(&self, topic_partition: &TopicPartition) -> usize {
        self.partitions
            .lock()
            .unwrap()
            .get(topic_partition)
            .map(PartitionOffsetLedger::depth)
            .unwrap_or_default()
    }

    /// Start a new generation for each partition, dropping its ledger. Called
    /// when a partition is revoked or assigned: Kafka redelivers it from the
    /// committed offset, which a kept ledger would reject as duplicate
    /// delivery, and work still in flight from the old assignment must not
    /// land on the new one.
    pub fn forget_partitions<'a>(&self, revoked: impl IntoIterator<Item = (&'a str, i32)>) {
        let mut partitions = self.partitions.lock().unwrap();
        let mut forgotten = 0;
        for (topic, partition) in revoked {
            let key = TopicPartition::new(topic, partition);
            let generation = partitions
                .get(&key)
                .map(PartitionOffsetLedger::generation)
                .unwrap_or_default();
            partitions.insert(key, PartitionOffsetLedger::new(generation + 1));
            forgotten += 1;
        }
        self.generations_version
            .fetch_add(forgotten, Ordering::Relaxed);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tp(topic: &str, partition: i32) -> TopicPartition {
        TopicPartition::new(topic, partition)
    }

    fn charge(ledger: &TopicOffsetLedger, tp: &TopicPartition, stamp: u64, offsets: &[i64]) {
        ledger
            .charge(
                tp,
                stamp,
                offsets.iter().map(|&offset| (Offset(offset), Charge::ZERO)),
            )
            .unwrap();
    }

    #[test]
    fn a_completed_batch_reports_its_frontier_and_drains() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);
        charge(&ledger, &p0, 0, &[11]);

        let settlement = ledger
            .settle(&p0, 0, [Offset(10), Offset(11)])
            .expect("live ledger settles");
        assert_eq!(settlement.frontier, Some(Offset(12)));

        assert_eq!(ledger.take_frontier(&p0), Some(Offset(12)));
        assert_eq!(ledger.depth(&p0), 0);
    }

    #[test]
    fn forgetting_a_partition_drops_its_ledger_and_advances_its_generation() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);
        assert_eq!(ledger.generations_version(), 0);

        ledger.forget_partitions([("events", 0)]);

        assert_eq!(ledger.depth(&p0), 0);
        assert_eq!(ledger.generation(&p0), 1);
        assert_eq!(ledger.generations_version(), 1);
    }

    #[test]
    fn forgetting_an_unseen_partition_still_opens_a_generation() {
        // A slice buffered before the revoke carries stamp 0; without a new
        // generation it would found the new assignment's ledger with stale offsets.
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        ledger.forget_partitions([("events", 0)]);

        assert_eq!(ledger.generation(&p0), 1);
        assert_eq!(
            ledger.charge(&p0, 0, [(Offset(10), Charge::ZERO)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 1
            })
        );
        assert_eq!(ledger.charge(&p0, 1, [(Offset(10), Charge::ZERO)]), Ok(1));
    }

    #[test]
    fn an_incomplete_prefix_reports_no_frontier_and_holds_offsets() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);
        charge(&ledger, &p0, 0, &[11]);

        let settlement = ledger
            .settle(&p0, 0, [Offset(11)])
            .expect("live ledger settles");
        assert_eq!(settlement.frontier, None);
        assert_eq!(settlement.depth, 2);
        assert_eq!(ledger.take_frontier(&p0), None);
        assert_eq!(ledger.depth(&p0), 2);

        // The late completion arrives with the next batch and the held
        // offsets drain.
        let settlement = ledger
            .settle(&p0, 0, [Offset(10)])
            .expect("live ledger settles");
        assert_eq!(settlement.frontier, Some(Offset(12)));
        assert_eq!(ledger.take_frontier(&p0), Some(Offset(12)));
        assert_eq!(ledger.depth(&p0), 0);
    }

    #[test]
    fn a_batch_spanning_partitions_settles_each_independently() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        let p1 = tp("events", 1);
        charge(&ledger, &p0, 0, &[10, 11]);
        charge(&ledger, &p1, 0, &[20, 21]);

        let settled = ledger
            .settle(&p0, 0, [Offset(10), Offset(11)])
            .expect("live ledger settles");
        assert_eq!(settled.frontier, Some(Offset(12)));
        let held = ledger
            .settle(&p1, 0, [Offset(21)])
            .expect("live ledger settles");
        assert_eq!(held.frontier, None);

        ledger.take_frontier(&p0);
        ledger.take_frontier(&p1);
        assert_eq!(ledger.depth(&p0), 0, "the settled partition drains");
        assert_eq!(ledger.depth(&p1), 2, "the held partition keeps its offsets");
    }

    #[test]
    fn completions_for_a_forgotten_partition_are_stale() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);
        ledger.forget_partitions([("events", 0)]);

        assert_eq!(
            ledger.settle(&p0, 0, [Offset(10)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 1
            })
        );
    }

    #[test]
    fn completions_for_a_never_charged_partition_are_stale() {
        let ledger = TopicOffsetLedger::new();
        assert_eq!(
            ledger.settle(&tp("events", 0), 0, [Offset(10)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 0
            })
        );
    }

    #[test]
    fn partitions_are_keyed_by_topic_and_partition() {
        let ledger = TopicOffsetLedger::new();
        let events = tp("events", 0);
        let overflow = tp("overflow", 0);
        charge(&ledger, &events, 0, &[10]);
        charge(&ledger, &overflow, 0, &[10]);

        ledger
            .settle(&events, 0, [Offset(10)])
            .expect("live ledger settles");
        ledger.take_frontier(&events);

        assert_eq!(ledger.depth(&events), 0);
        assert_eq!(ledger.depth(&overflow), 1);
    }

    #[test]
    fn stale_completions_from_a_previous_assignment_are_dropped() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);

        // The partition is revoked and reassigned to this consumer while the
        // batch is still in flight; the redelivery recharges the same offset.
        ledger.forget_partitions([("events", 0)]);
        charge(&ledger, &p0, 1, &[10]);

        assert_eq!(
            ledger.settle(&p0, 0, [Offset(10)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 1
            })
        );
        assert_eq!(
            ledger.depth(&p0),
            1,
            "the redelivered offset stays uncompleted"
        );

        // The redelivery's own completion settles the new assignment's ledger.
        ledger
            .settle(&p0, 1, [Offset(10)])
            .expect("current-generation batch settles");
        ledger.take_frontier(&p0);
        assert_eq!(ledger.depth(&p0), 0);
    }

    #[test]
    fn a_reassignment_affects_only_its_own_partition() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        let p1 = tp("events", 1);
        charge(&ledger, &p0, 0, &[10]);
        charge(&ledger, &p1, 0, &[20]);

        // Only partition 0 is revoked and reassigned.
        ledger.forget_partitions([("events", 0)]);
        charge(&ledger, &p0, 1, &[10]);
        assert_eq!(
            ledger.generation(&p1),
            0,
            "partition 1 keeps its generation"
        );

        assert_eq!(
            ledger.settle(&p0, 0, [Offset(10)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 1
            })
        );
        ledger
            .settle(&p1, 0, [Offset(20)])
            .expect("untouched partition settles");
        ledger.take_frontier(&p1);

        assert_eq!(
            ledger.depth(&p0),
            1,
            "the reassigned partition ignores the stale completion"
        );
        assert_eq!(
            ledger.depth(&p1),
            0,
            "the untouched partition completes and drains"
        );
    }

    #[test]
    fn slices_spanning_another_partitions_generation_change_still_charge() {
        let ledger = TopicOffsetLedger::new();
        let p1 = tp("events", 1);
        charge(&ledger, &p1, 0, &[20]);

        // Another partition's reassignment moves the generations version;
        // this partition's generation and ledger are untouched.
        ledger.forget_partitions([("events", 0)]);
        assert_eq!(ledger.generations_version(), 1);
        charge(&ledger, &p1, 0, &[21]);
        assert_eq!(ledger.depth(&p1), 2);

        ledger
            .settle(&p1, 0, [Offset(20), Offset(21)])
            .expect("surviving ledger settles");
        ledger.take_frontier(&p1);
        assert_eq!(ledger.depth(&p1), 0, "no message is lost");
    }

    #[test]
    fn a_partition_lost_for_a_generation_returns_under_a_later_one() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);

        // The partition leaves for another consumer and returns later; both
        // callbacks forget it, and the in-flight batch settles in between.
        ledger.forget_partitions([("events", 0)]);
        ledger.forget_partitions([("events", 0)]);
        assert_eq!(ledger.generation(&p0), 2);

        assert_eq!(
            ledger.settle(&p0, 0, [Offset(10)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 2
            })
        );
        assert_eq!(ledger.depth(&p0), 0, "no ledger, nothing lands");

        charge(&ledger, &p0, 2, &[10]);
        ledger
            .settle(&p0, 2, [Offset(10)])
            .expect("the new assignment settles");
        ledger.take_frontier(&p0);
        assert_eq!(ledger.depth(&p0), 0);
    }

    #[test]
    fn slices_from_every_older_generation_cannot_refound_a_dropped_ledger() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);
        ledger.forget_partitions([("events", 0)]);
        ledger.forget_partitions([("events", 0)]);

        assert_eq!(
            ledger.charge(&p0, 0, [(Offset(10), Charge::ZERO)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 2
            })
        );
        assert_eq!(
            ledger.charge(&p0, 1, [(Offset(10), Charge::ZERO)]),
            Err(Rejection::Stale {
                stamp: 1,
                generation: 2
            })
        );
        assert_eq!(ledger.depth(&p0), 0);

        assert_eq!(ledger.charge(&p0, 2, [(Offset(10), Charge::ZERO)]), Ok(1));
    }

    #[test]
    fn a_violating_charge_resets_the_partition_to_a_new_generation() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10, 11]);

        // A duplicate delivery under the same generation is a contract
        // violation, not a rebalance: the ledger cannot trust its window.
        assert_eq!(
            ledger.charge(&p0, 0, [(Offset(11), Charge::ZERO)]),
            Err(Rejection::Violation(LedgerError::OffsetNotAboveWindow {
                offset: Offset(11),
                next: Offset(12),
            }))
        );
        assert_eq!(ledger.depth(&p0), 0, "the window is discarded");
        assert_eq!(ledger.generation(&p0), 1);
        assert_eq!(ledger.generations_version(), 1);

        // In-flight work from before the reset drops as stale; the next
        // delivery under the new generation founds a fresh ledger.
        assert_eq!(
            ledger.settle(&p0, 0, [Offset(10)]),
            Err(Rejection::Stale {
                stamp: 0,
                generation: 1
            })
        );
        assert_eq!(ledger.charge(&p0, 1, [(Offset(12), Charge::ZERO)]), Ok(1));
    }

    #[test]
    fn a_violating_completion_resets_the_partition_to_a_new_generation() {
        let ledger = TopicOffsetLedger::new();
        let p0 = tp("events", 0);
        charge(&ledger, &p0, 0, &[10]);

        assert_eq!(
            ledger.settle(&p0, 0, [Offset(15)]),
            Err(Rejection::Violation(LedgerError::CompletionUncharged {
                offset: Offset(15)
            }))
        );
        assert_eq!(ledger.depth(&p0), 0);
        assert_eq!(ledger.generation(&p0), 1);
        assert_eq!(ledger.take_frontier(&p0), None);
    }
}
