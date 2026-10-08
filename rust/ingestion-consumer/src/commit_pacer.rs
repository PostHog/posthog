//! Commit pacing for the ingestion consumer. The consumer hands over each
//! partition's frontier as it takes it from the ledger, then asks the pacer
//! what is due and commits that in one call. The pacer holds no I/O.
//!
//! This pacer is immediate: every frontier handed over is due on the next
//! take, so the consumer commits once per poll. Coalescing frontiers on an
//! interval is a later pacer; see the driver-model plan, cycle 8.

use std::collections::HashMap;
use std::sync::Mutex;

use common_kafka_consumer::{Offset, TakenFrontier, TopicPartition};

/// Hands out every frontier handed to it on the next take. The commit
/// sentinel wraps it to check what passes through.
#[derive(Default)]
pub struct ImmediateCommitPacer {
    /// The next-to-read offset each partition is ready to commit. Frontiers
    /// only move forward, so the latest one covers every earlier one.
    pending: Mutex<HashMap<TopicPartition, Offset>>,
}

impl ImmediateCommitPacer {
    pub fn new() -> Self {
        Self::default()
    }

    /// Replace the partition's pending offset; frontiers only move forward.
    pub fn advance_frontier(&self, topic_partition: &TopicPartition, taken: TakenFrontier) {
        self.pending
            .lock()
            .unwrap()
            .insert(topic_partition.clone(), taken.offset);
    }

    /// Partitions leaving the assignment: drop whatever is held for them. A
    /// commit issued for a partition another member now owns could move the
    /// group's offset back behind that member's progress, so the frontier
    /// goes with the partition.
    pub fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        let mut pending = self.pending.lock().unwrap();
        for topic_partition in topic_partitions {
            pending.remove(topic_partition);
        }
    }

    /// The offsets due for commit: everything pending, or `None` with
    /// nothing pending.
    pub fn take_due(&self) -> Option<HashMap<TopicPartition, Offset>> {
        let mut pending = self.pending.lock().unwrap();
        if pending.is_empty() {
            return None;
        }
        Some(std::mem::take(&mut pending))
    }
}

#[cfg(test)]
pub(crate) mod test_support {
    use common_kafka_consumer::Charge;

    use super::*;

    pub(crate) fn tp(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    /// A take that started at window base `first` and reached `offset`.
    pub(crate) fn taken(first: i64, offset: i64) -> TakenFrontier {
        TakenFrontier {
            first: Offset(first),
            offset: Offset(offset),
            charge: Charge::ZERO,
            gap_offset_count: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::*;
    use super::*;

    #[test]
    fn a_pending_frontier_is_due_on_the_next_take() {
        let pacer = ImmediateCommitPacer::new();
        pacer.advance_frontier(&tp(0), taken(0, 10));

        let offsets = pacer.take_due().expect("due");
        assert_eq!(offsets, HashMap::from([(tp(0), Offset(10))]));
        assert!(pacer.take_due().is_none(), "a take leaves nothing behind");
    }

    #[test]
    fn the_latest_frontier_per_partition_is_what_goes_out() {
        let pacer = ImmediateCommitPacer::new();
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.advance_frontier(&tp(1), taken(0, 20));
        pacer.advance_frontier(&tp(0), taken(10, 12));

        let offsets = pacer.take_due().expect("due");
        assert_eq!(
            offsets,
            HashMap::from([(tp(0), Offset(12)), (tp(1), Offset(20))])
        );
    }

    #[test]
    fn a_forgotten_partition_is_not_committed() {
        let pacer = ImmediateCommitPacer::new();
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.advance_frontier(&tp(1), taken(0, 20));

        pacer.forget_partitions(&[tp(0)]);

        assert_eq!(
            pacer.take_due().expect("due"),
            HashMap::from([(tp(1), Offset(20))])
        );
    }
}
