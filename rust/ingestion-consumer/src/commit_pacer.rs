//! Commit pacing for the ingestion consumer. A settlement hands over each
//! partition's frontier as it takes it from the ledger; the consumer asks the
//! pacer what is due and commits that in one call. The pacer holds no I/O.
//!
//! The pacer keeps the latest frontier per partition, with the charge of every
//! take since the last commit, and hands them out at most once per interval.
//! A zero interval makes every take due.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Held, Offset, TakenFrontier, TopicPartition};

pub struct CommitPacer {
    interval: Duration,
    frontiers: HashMap<TopicPartition, PendingFrontier>,
    last_take: Option<Instant>,
}

struct PendingFrontier {
    offset: Offset,
    held: Held,
}

impl CommitPacer {
    pub fn immediate() -> Self {
        Self::every(Duration::ZERO)
    }

    pub fn every(interval: Duration) -> Self {
        Self {
            interval,
            frontiers: HashMap::new(),
            last_take: None,
        }
    }

    /// Replace the partition's pending offset; frontiers only move forward.
    pub fn advance_frontier(&mut self, topic_partition: &TopicPartition, taken: TakenFrontier) {
        let taken_offsets = usize::try_from(taken.offset - taken.first)
            .expect("a frontier is above its window base");
        let pending = self
            .frontiers
            .entry(topic_partition.clone())
            .or_insert(PendingFrontier {
                offset: taken.offset,
                held: Held::default(),
            });
        pending.offset = taken.offset;
        pending.held += Held {
            offsets: taken_offsets,
            charge: taken.charge,
        };
    }

    pub fn pending(&self, topic_partition: &TopicPartition) -> Held {
        self.frontiers
            .get(topic_partition)
            .map(|pending| pending.held)
            .unwrap_or_default()
    }

    /// Partitions leaving the assignment: drop whatever is held for them. A
    /// commit issued for a partition another member now owns could move the
    /// group's offset back behind that member's progress, so the frontier
    /// goes with the partition.
    pub fn forget_partitions(&mut self, topic_partitions: &[TopicPartition]) {
        for topic_partition in topic_partitions {
            self.frontiers.remove(topic_partition);
        }
    }

    pub fn take_due(&mut self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        if self.frontiers.is_empty() {
            return None;
        }
        if self
            .last_take
            .is_some_and(|last| now.duration_since(last) < self.interval)
        {
            return None;
        }
        self.last_take = Some(now);
        self.take_all()
    }

    pub fn take_all(&mut self) -> Option<HashMap<TopicPartition, Offset>> {
        if self.frontiers.is_empty() {
            return None;
        }
        Some(
            self.frontiers
                .drain()
                .map(|(topic_partition, pending)| (topic_partition, pending.offset))
                .collect(),
        )
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
        let mut pacer = CommitPacer::immediate();
        pacer.advance_frontier(&tp(0), taken(0, 10));

        let offsets = pacer.take_due(Instant::now()).expect("due");
        assert_eq!(offsets, HashMap::from([(tp(0), Offset(10))]));
        assert!(
            pacer.take_due(Instant::now()).is_none(),
            "a take leaves nothing behind"
        );
    }

    #[test]
    fn the_latest_frontier_per_partition_is_what_goes_out() {
        let mut pacer = CommitPacer::immediate();
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.advance_frontier(&tp(1), taken(0, 20));
        pacer.advance_frontier(&tp(0), taken(10, 12));

        let offsets = pacer.take_due(Instant::now()).expect("due");
        assert_eq!(
            offsets,
            HashMap::from([(tp(0), Offset(12)), (tp(1), Offset(20))])
        );
    }

    #[test]
    fn a_forgotten_partition_is_not_committed() {
        let mut pacer = CommitPacer::immediate();
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.advance_frontier(&tp(1), taken(0, 20));

        pacer.forget_partitions(&[tp(0)]);

        assert_eq!(
            pacer.take_due(Instant::now()).expect("due"),
            HashMap::from([(tp(1), Offset(20))])
        );
    }

    #[test]
    fn frontiers_handed_over_within_the_interval_wait_for_it() {
        let mut pacer = CommitPacer::every(Duration::from_millis(500));
        let start = Instant::now();

        pacer.advance_frontier(&tp(0), taken(0, 10));
        assert!(
            pacer.take_due(start).is_some(),
            "the first frontier goes out at once"
        );

        pacer.advance_frontier(&tp(0), taken(10, 12));
        pacer.advance_frontier(&tp(1), taken(0, 20));
        assert!(
            pacer.take_due(start + Duration::from_millis(100)).is_none(),
            "inside the interval nothing goes out"
        );
        assert_eq!(
            pacer
                .take_due(start + Duration::from_millis(500))
                .expect("due"),
            HashMap::from([(tp(0), Offset(12)), (tp(1), Offset(20))]),
            "one take carries everything that arrived during the interval"
        );
    }

    #[test]
    fn an_empty_take_does_not_start_the_interval() {
        let mut pacer = CommitPacer::every(Duration::from_millis(500));
        let start = Instant::now();
        assert!(pacer.take_due(start).is_none());

        pacer.advance_frontier(&tp(0), taken(0, 10));
        assert!(pacer.take_due(start + Duration::from_millis(100)).is_some());
    }

    #[test]
    fn take_all_ignores_the_interval() {
        let mut pacer = CommitPacer::every(Duration::from_secs(3600));
        let start = Instant::now();
        pacer.advance_frontier(&tp(0), taken(0, 10));
        pacer.take_due(start).expect("due");

        pacer.advance_frontier(&tp(0), taken(10, 12));
        assert!(pacer.take_due(start + Duration::from_secs(1)).is_none());
        assert_eq!(
            pacer.take_all().expect("pending"),
            HashMap::from([(tp(0), Offset(12))])
        );
    }
}
