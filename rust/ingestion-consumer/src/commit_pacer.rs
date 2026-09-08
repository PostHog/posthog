//! Commit pacing for the ingestion consumer. The consumer hands over each
//! partition's frontier as it takes it from the ledger and asks the pacer
//! on every tick. The pacer holds the latest frontier per partition and
//! hands them out once the interval has elapsed. The consumer commits them
//! in one call, so the commit rate is bounded by the interval rather than by
//! how often frontiers move. The pacer holds no I/O.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Offset, TakenFrontier, TopicPartition};

#[derive(Default)]
struct State {
    /// The next-to-read offset each partition is ready to commit. Frontiers
    /// only move forward, so the latest one covers every earlier one.
    pending: HashMap<TopicPartition, Offset>,
    last_take: Option<Instant>,
}

/// Hands out the pending offsets at most once per `interval`. The commit
/// sentinel wraps it to check what passes through.
pub struct CommitPacer {
    state: Mutex<State>,
    interval: Duration,
}

impl CommitPacer {
    pub fn new(interval: Duration) -> Self {
        Self {
            state: Mutex::new(State::default()),
            interval,
        }
    }

    /// The consumer took a partition's frontier from the ledger.
    pub fn on_frontier(&self, topic_partition: &TopicPartition, taken: TakenFrontier) {
        self.state
            .lock()
            .unwrap()
            .pending
            .insert(topic_partition.clone(), taken.offset);
    }

    /// Partitions leaving the assignment: drop whatever is held for them. A
    /// commit issued for a partition another member now owns could move the
    /// group's offset back behind that member's progress, so the frontier
    /// goes with the partition.
    pub fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        let mut state = self.state.lock().unwrap();
        for topic_partition in topic_partitions {
            state.pending.remove(topic_partition);
        }
    }

    /// The offsets due for commit: the pending ones once the interval has
    /// elapsed since the last take, and `None` inside the interval or with
    /// nothing pending. Asking more often than the interval costs nothing.
    pub fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        let mut state = self.state.lock().unwrap();
        let inside_interval = state
            .last_take
            .is_some_and(|last| now < last + self.interval);
        // An empty take does not start an interval, so a frontier arriving
        // after a quiet spell goes out on the next call.
        if inside_interval || state.pending.is_empty() {
            return None;
        }
        state.last_take = Some(now);
        Some(std::mem::take(&mut state.pending))
    }

    /// Everything ready to commit, regardless of the interval.
    pub fn drain(&self) -> HashMap<TopicPartition, Offset> {
        std::mem::take(&mut self.state.lock().unwrap().pending)
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

    const INTERVAL: Duration = Duration::from_millis(500);

    #[test]
    fn the_first_take_with_a_pending_frontier_hands_it_out() {
        let pacer = CommitPacer::new(INTERVAL);
        pacer.on_frontier(&tp(0), taken(0, 10));

        let offsets = pacer.take_due(Instant::now()).expect("due");
        assert_eq!(offsets, HashMap::from([(tp(0), Offset(10))]));
    }

    #[test]
    fn the_latest_frontier_per_partition_is_what_goes_out() {
        let pacer = CommitPacer::new(INTERVAL);
        pacer.on_frontier(&tp(0), taken(0, 10));
        pacer.on_frontier(&tp(1), taken(0, 20));
        pacer.on_frontier(&tp(0), taken(10, 12));

        let offsets = pacer.take_due(Instant::now()).expect("due");
        assert_eq!(
            offsets,
            HashMap::from([(tp(0), Offset(12)), (tp(1), Offset(20))])
        );
    }

    #[test]
    fn a_take_inside_the_interval_hands_out_nothing_and_keeps_the_frontier() {
        let pacer = CommitPacer::new(INTERVAL);
        let start = Instant::now();
        pacer.on_frontier(&tp(0), taken(0, 10));
        pacer.take_due(start).expect("due");
        pacer.on_frontier(&tp(1), taken(0, 20));

        assert!(pacer.take_due(start + INTERVAL / 2).is_none());
        assert_eq!(
            pacer.take_due(start + INTERVAL).expect("due again"),
            HashMap::from([(tp(1), Offset(20))])
        );
    }

    #[test]
    fn an_empty_take_does_not_start_an_interval() {
        let pacer = CommitPacer::new(INTERVAL);
        let start = Instant::now();

        assert!(pacer.take_due(start).is_none());
        pacer.on_frontier(&tp(0), taken(0, 10));

        assert!(pacer.take_due(start + Duration::from_millis(1)).is_some());
    }

    #[test]
    fn a_drain_ignores_the_interval() {
        let pacer = CommitPacer::new(INTERVAL);
        let start = Instant::now();
        pacer.on_frontier(&tp(0), taken(0, 10));
        pacer.take_due(start).expect("due");
        pacer.on_frontier(&tp(1), taken(0, 20));

        assert_eq!(pacer.drain(), HashMap::from([(tp(1), Offset(20))]));
        assert!(pacer.drain().is_empty(), "a drain leaves nothing behind");
    }

    #[test]
    fn a_forgotten_partition_is_not_committed() {
        let pacer = CommitPacer::new(INTERVAL);
        pacer.on_frontier(&tp(0), taken(0, 10));
        pacer.on_frontier(&tp(1), taken(0, 20));

        pacer.forget_partitions(&[tp(0)]);

        assert_eq!(pacer.drain(), HashMap::from([(tp(1), Offset(20))]));
    }
}
