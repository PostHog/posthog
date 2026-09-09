//! Commit pacing for the ingestion consumer. The consumer hands over each
//! partition's frontier as it takes it from the ledger, then asks the pacer
//! what is due and commits that in one call. The pacer holds no I/O.
//!
//! With no interval, every frontier handed over is due on the next take, so a
//! consumer that asks right after settling a poll commits once per poll. With
//! an interval, the pacer keeps the latest frontier per partition and hands
//! them out at most once per interval, so frontiers that arrive per group
//! completion coalesce into one commit.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Offset, TakenFrontier, TopicPartition};

use crate::config::CompletionGranularity;

/// Holds the latest frontier per partition and says when they go out. The
/// commit sentinel wraps it to check what passes through.
pub struct CommitPacer {
    /// The least time between two takes that hand something out. Zero makes
    /// every take hand out what is pending.
    interval: Duration,
    pending: Mutex<Pending>,
}

#[derive(Default)]
struct Pending {
    /// The next-to-read offset each partition is ready to commit. Frontiers
    /// only move forward, so the latest one covers every earlier one.
    frontiers: HashMap<TopicPartition, Offset>,
    /// When the last take handed something out; `None` before the first.
    last_take: Option<Instant>,
}

impl CommitPacer {
    /// Every frontier is due on the next take.
    pub fn immediate() -> Self {
        Self::every(Duration::ZERO)
    }

    /// Frontiers are due at most once per `interval`.
    pub fn every(interval: Duration) -> Self {
        Self {
            interval,
            pending: Mutex::new(Pending::default()),
        }
    }

    /// The pacer a completion granularity commits through. A poll commits as
    /// it completes; groups complete one send at a time, so their frontiers
    /// coalesce on `interval`.
    pub fn for_granularity(granularity: CompletionGranularity, interval: Duration) -> Self {
        match granularity {
            CompletionGranularity::Poll => Self::immediate(),
            CompletionGranularity::Group => Self::every(interval),
        }
    }

    /// Replace the partition's pending offset; frontiers only move forward.
    pub fn advance_frontier(&self, topic_partition: &TopicPartition, taken: TakenFrontier) {
        self.pending
            .lock()
            .unwrap()
            .frontiers
            .insert(topic_partition.clone(), taken.offset);
    }

    /// Partitions leaving the assignment: drop whatever is held for them. A
    /// commit issued for a partition another member now owns could move the
    /// group's offset back behind that member's progress, so the frontier
    /// goes with the partition.
    pub fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        let mut pending = self.pending.lock().unwrap();
        for topic_partition in topic_partitions {
            pending.frontiers.remove(topic_partition);
        }
    }

    /// The offsets due for commit at `now`: everything pending once the
    /// interval since the last take has passed, else `None`. A take with
    /// nothing pending leaves the interval where it was, so the first
    /// frontier after a quiet spell goes out at once.
    pub fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        let mut pending = self.pending.lock().unwrap();
        if pending.frontiers.is_empty() {
            return None;
        }
        if pending
            .last_take
            .is_some_and(|last| now.duration_since(last) < self.interval)
        {
            return None;
        }
        pending.last_take = Some(now);
        Some(std::mem::take(&mut pending.frontiers))
    }

    /// Everything pending, whatever the interval. For the way out: accepted
    /// work still held here would replay after a restart.
    pub fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>> {
        let mut pending = self.pending.lock().unwrap();
        if pending.frontiers.is_empty() {
            return None;
        }
        Some(std::mem::take(&mut pending.frontiers))
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
        let pacer = CommitPacer::immediate();
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
        let pacer = CommitPacer::immediate();
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
        let pacer = CommitPacer::immediate();
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
        let pacer = CommitPacer::every(Duration::from_millis(500));
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
    fn take_all_ignores_the_interval() {
        let pacer = CommitPacer::every(Duration::from_secs(3600));
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
