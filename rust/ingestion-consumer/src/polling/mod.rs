//! How the consumer loop reads Kafka and waits for completions. A strategy
//! decides what the loop does next and returns it as a [`Step`]; the consumer
//! carries the step out against the Kafka client and the batcher.

mod capped;
mod collector;
mod poll;

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use common_kafka_consumer::{GroupCompletion, TopicPartition};
use lifecycle::Handle;
use tokio::sync::mpsc;

use crate::debug_recorder::DebugRecorder;
use crate::settlement::{Commit, Settlement};

pub(crate) use capped::CappedPolling;
pub(crate) use collector::{Collector, PollLimits};
pub(crate) use poll::{
    debug_partition_offsets, debug_partition_spans, BatchStats, CollectedBatch, InFlightPoll,
    PartitionDeliveries,
};

pub(crate) enum Step {
    /// Charge the poll, submit it to the batcher, and hand it back through
    /// [`PollingStrategy::submitted`].
    Submit(CollectedBatch),
    /// Submit the offsets and resume the partitions.
    Commit(Commit),
    /// Shutdown was signalled: the batcher takes no new groups.
    BeginShutdown,
    /// Shutdown drained the in-flight work.
    Stop,
    /// A poll could not be collected, dispatched, or completed.
    Fail(anyhow::Error),
}

pub(crate) struct LoopParts {
    pub(crate) collector: Collector,
    pub(crate) completions: mpsc::UnboundedReceiver<GroupCompletion>,
    pub(crate) errors: mpsc::UnboundedReceiver<String>,
    pub(crate) settlement: Arc<dyn Settlement>,
    pub(crate) fetching: Arc<FetchingPartitions>,
    /// Partitions revoked since the loop last looked, fed by the rebalance
    /// callback.
    pub(crate) revoked_partitions: Arc<Mutex<Vec<RevokedPartition>>>,
    pub(crate) handle: Handle,
    pub(crate) commit_tick: Duration,
    pub(crate) group_id: String,
    pub(crate) debug_recorder: Option<Arc<DebugRecorder>>,
}

pub(crate) enum PollingStrategy {
    Capped(CappedPolling),
}

impl PollingStrategy {
    pub(crate) async fn next(&mut self) -> Step {
        match self {
            Self::Capped(capped) => capped.next().await,
        }
    }

    pub(crate) fn submitted(&mut self, poll: InFlightPoll) {
        match self {
            Self::Capped(capped) => capped.submitted(poll),
        }
    }
}

/// A partition revocation stamped with the ledger generation started by the
/// revoke. Poll slices from earlier generations are stale; slices collected
/// after a later reassignment must survive a delayed notification.
#[derive(Clone, Debug)]
pub(crate) struct RevokedPartition {
    pub(crate) topic_partition: TopicPartition,
    pub(crate) generation: u64,
}

#[derive(Default)]
struct Partitions {
    fetching: HashSet<TopicPartition>,
    paused: HashSet<TopicPartition>,
}

#[derive(Default)]
pub(crate) struct FetchingPartitions {
    partitions: Mutex<Partitions>,
    all_paused: AtomicBool,
}

impl FetchingPartitions {
    pub(crate) fn assigned(&self, topic_partitions: &[TopicPartition]) {
        self.update(|partitions| {
            for topic_partition in topic_partitions {
                partitions.paused.remove(topic_partition);
                partitions.fetching.insert(topic_partition.clone());
            }
        });
    }

    pub(crate) fn revoked(&self, topic_partitions: &[TopicPartition]) {
        self.update(|partitions| {
            for topic_partition in topic_partitions {
                partitions.paused.remove(topic_partition);
                partitions.fetching.remove(topic_partition);
            }
        });
    }

    pub(crate) fn paused(&self, topic_partition: &TopicPartition) {
        self.update(|partitions| {
            if partitions.fetching.remove(topic_partition) {
                partitions.paused.insert(topic_partition.clone());
            }
        });
    }

    pub(crate) fn resumed(&self, topic_partition: &TopicPartition) {
        self.update(|partitions| {
            if partitions.paused.remove(topic_partition) {
                partitions.fetching.insert(topic_partition.clone());
            }
        });
    }

    pub(crate) fn all_paused(&self) -> bool {
        self.all_paused.load(Ordering::Relaxed)
    }

    fn update(&self, change: impl FnOnce(&mut Partitions)) {
        let mut partitions = self.partitions.lock().unwrap();
        change(&mut partitions);
        self.all_paused.store(
            !partitions.paused.is_empty() && partitions.fetching.is_empty(),
            Ordering::Relaxed,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn partitions(numbers: &[i32]) -> Vec<TopicPartition> {
        numbers
            .iter()
            .map(|&number| TopicPartition::new("events", number))
            .collect()
    }

    #[test]
    fn every_partition_is_paused_only_while_none_is_fetching() {
        let fetching = FetchingPartitions::default();
        assert!(!fetching.all_paused(), "nothing is assigned");

        fetching.assigned(&partitions(&[0, 1]));
        fetching.paused(&TopicPartition::new("events", 0));
        assert!(!fetching.all_paused(), "partition 1 still fetches");

        fetching.paused(&TopicPartition::new("events", 1));
        assert!(fetching.all_paused());

        fetching.resumed(&TopicPartition::new("events", 1));
        assert!(!fetching.all_paused());
    }

    #[test]
    fn a_rebalance_changes_which_partitions_must_be_paused() {
        let fetching = FetchingPartitions::default();
        fetching.assigned(&partitions(&[0, 1]));
        fetching.paused(&TopicPartition::new("events", 0));

        fetching.revoked(&partitions(&[1]));
        assert!(fetching.all_paused(), "only the paused partition is left");

        fetching.assigned(&partitions(&[0]));
        assert!(
            !fetching.all_paused(),
            "a reassigned partition starts fetching"
        );
    }

    #[test]
    fn a_partition_that_is_not_assigned_neither_pauses_nor_resumes() {
        let fetching = FetchingPartitions::default();

        fetching.paused(&TopicPartition::new("events", 0));
        assert!(!fetching.all_paused());

        fetching.resumed(&TopicPartition::new("events", 0));
        assert!(!fetching.all_paused());
    }
}
