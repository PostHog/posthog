//! Offset commits for the ingestion consumer. The consumer hands over each
//! partition's frontier as it takes it from the ledger and ticks the manager
//! from its wake-up timer. The manager decides when the interval has elapsed
//! and answers with the offsets to commit, the latest per partition, in one
//! batch. The consumer commits them. The commit rate is bounded by the
//! interval rather than by how often frontiers move.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Offset, TakenFrontier, TopicPartition};

/// Where the consumer's frontiers go, and what it asks on every tick. Holds
/// no I/O: the consumer commits what it is given. Implemented by
/// [`CommitManager`]; the commit sentinel wraps an implementation to check
/// what passes through.
pub trait Committer: Send + Sync {
    /// The consumer took a partition's frontier from the ledger.
    fn on_frontier(&self, topic_partition: &TopicPartition, taken: TakenFrontier);

    /// Partitions leaving the assignment: drop whatever is held for them.
    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);

    /// One tick of the consumer's wake-up timer. The offsets to commit now,
    /// at most once per interval; `None` when nothing is due.
    fn try_commit(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>>;

    /// Everything ready to commit, regardless of the interval.
    fn drain(&self) -> HashMap<TopicPartition, Offset>;
}

#[derive(Default)]
struct State {
    /// The next-to-read offset each partition is ready to commit. Frontiers
    /// only move forward, so the latest one covers every earlier one.
    pending: HashMap<TopicPartition, Offset>,
    /// When the last commit went out; `None` before the first.
    last_commit: Option<Instant>,
}

/// Hands out the pending offsets at most once per `interval`.
pub struct CommitManager {
    state: Mutex<State>,
    interval: Duration,
}

impl CommitManager {
    pub fn new(interval: Duration) -> Self {
        Self {
            state: Mutex::new(State::default()),
            interval,
        }
    }
}

impl Committer for CommitManager {
    fn on_frontier(&self, topic_partition: &TopicPartition, taken: TakenFrontier) {
        self.state
            .lock()
            .unwrap()
            .pending
            .insert(topic_partition.clone(), taken.offset);
    }

    /// A commit issued for a partition another member now owns could move the
    /// group's offset back behind that member's progress, so the frontier
    /// goes with the partition.
    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        let mut state = self.state.lock().unwrap();
        for topic_partition in topic_partitions {
            state.pending.remove(topic_partition);
        }
    }

    fn try_commit(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        let mut state = self.state.lock().unwrap();
        let inside_interval = state
            .last_commit
            .is_some_and(|last| now < last + self.interval);
        // An idle tick does not start an interval, so a frontier arriving
        // after a quiet spell goes out on the next tick.
        if inside_interval || state.pending.is_empty() {
            return None;
        }
        state.last_commit = Some(now);
        Some(std::mem::take(&mut state.pending))
    }

    fn drain(&self) -> HashMap<TopicPartition, Offset> {
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
    fn the_first_tick_with_a_pending_frontier_commits_at_once() {
        let manager = CommitManager::new(INTERVAL);
        manager.on_frontier(&tp(0), taken(0, 10));

        let offsets = manager.try_commit(Instant::now()).expect("due");
        assert_eq!(offsets, HashMap::from([(tp(0), Offset(10))]));
    }

    #[test]
    fn the_latest_frontier_per_partition_is_what_commits() {
        let manager = CommitManager::new(INTERVAL);
        manager.on_frontier(&tp(0), taken(0, 10));
        manager.on_frontier(&tp(1), taken(0, 20));
        manager.on_frontier(&tp(0), taken(10, 12));

        let offsets = manager.try_commit(Instant::now()).expect("due");
        assert_eq!(
            offsets,
            HashMap::from([(tp(0), Offset(12)), (tp(1), Offset(20))])
        );
    }

    #[test]
    fn a_tick_inside_the_interval_commits_nothing_and_keeps_the_frontier() {
        let manager = CommitManager::new(INTERVAL);
        let start = Instant::now();
        manager.on_frontier(&tp(0), taken(0, 10));
        manager.try_commit(start).expect("due");
        manager.on_frontier(&tp(1), taken(0, 20));

        assert!(manager.try_commit(start + INTERVAL / 2).is_none());
        assert_eq!(
            manager.try_commit(start + INTERVAL).expect("due again"),
            HashMap::from([(tp(1), Offset(20))])
        );
    }

    #[test]
    fn an_idle_tick_does_not_start_an_interval() {
        let manager = CommitManager::new(INTERVAL);
        let start = Instant::now();

        assert!(manager.try_commit(start).is_none());
        manager.on_frontier(&tp(0), taken(0, 10));

        assert!(manager
            .try_commit(start + Duration::from_millis(1))
            .is_some());
    }

    #[test]
    fn a_drain_ignores_the_interval() {
        let manager = CommitManager::new(INTERVAL);
        let start = Instant::now();
        manager.on_frontier(&tp(0), taken(0, 10));
        manager.try_commit(start).expect("due");
        manager.on_frontier(&tp(1), taken(0, 20));

        assert_eq!(manager.drain(), HashMap::from([(tp(1), Offset(20))]));
        assert!(manager.drain().is_empty(), "a drain leaves nothing behind");
    }

    #[test]
    fn a_forgotten_partition_is_not_committed() {
        let manager = CommitManager::new(INTERVAL);
        manager.on_frontier(&tp(0), taken(0, 10));
        manager.on_frontier(&tp(1), taken(0, 20));

        manager.forget_partitions(&[tp(0)]);

        assert_eq!(manager.drain(), HashMap::from([(tp(1), Offset(20))]));
    }
}
