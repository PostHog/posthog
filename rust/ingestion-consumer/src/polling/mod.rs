//! How the consumer loop reads Kafka and waits for completions. A strategy
//! decides what the loop does next and returns it as a [`Step`]; the consumer
//! carries the step out against the Kafka client and the batcher.

mod capped;
mod collector;
mod continuous;
mod poll;

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use common_kafka_consumer::{GroupCompletion, TopicPartition};
use lifecycle::Handle;
use tokio::sync::mpsc;
use tracing::warn;

use crate::charge_limit::ChargeLimit;
use crate::config::{CompletionGranularity, Polling};
use crate::debug_recorder::DebugRecorder;
use crate::partition_budget::BudgetLimits;
use crate::settlement::{Commit, Settlement};

pub(crate) use capped::CappedPolling;
pub(crate) use collector::{Collector, PollLimits};
pub(crate) use continuous::ContinuousPolling;
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
    Capped(Box<CappedPolling>),
    Continuous(Box<ContinuousPolling>),
}

impl PollingStrategy {
    pub(crate) fn new(selected: Selected, parts: LoopParts) -> Self {
        match selected {
            Selected::Capped {
                max_in_flight_polls,
            } => Self::Capped(Box::new(CappedPolling::new(parts, max_in_flight_polls))),
            Selected::Continuous { in_flight } => {
                Self::Continuous(Box::new(ContinuousPolling::new(parts, in_flight)))
            }
        }
    }

    pub(crate) async fn next(&mut self) -> Step {
        match self {
            Self::Capped(capped) => capped.next().await,
            Self::Continuous(continuous) => continuous.next().await,
        }
    }

    pub(crate) fn submitted(&mut self, poll: InFlightPoll) {
        match self {
            Self::Capped(capped) => capped.submitted(poll),
            Self::Continuous(continuous) => continuous.submitted(poll),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Selected {
    Capped { max_in_flight_polls: usize },
    Continuous { in_flight: ChargeLimit },
}

/// Continuous polling needs `group` granularity, because at `poll` a commit
/// waits for the whole oldest poll. It needs a budget and an in-flight limit,
/// because without the admission cap they are the only bounds. Without all
/// three the capped strategy runs, so a lane rolled back to `poll` needs no
/// second setting changed.
pub(crate) fn select(
    polling: Polling,
    granularity: CompletionGranularity,
    budget: &BudgetLimits,
    in_flight: ChargeLimit,
    max_in_flight_polls: usize,
) -> Selected {
    let capped = Selected::Capped {
        max_in_flight_polls,
    };
    if polling == Polling::Capped {
        return capped;
    }
    let missing: Vec<&str> = [
        (
            granularity != CompletionGranularity::Group,
            "CONSUMER_COMPLETION_GRANULARITY=group",
        ),
        (!budget.is_set(), "a partition budget"),
        (!in_flight.is_set(), "an in-flight limit"),
    ]
    .into_iter()
    .filter_map(|(missing, requirement)| missing.then_some(requirement))
    .collect();
    if missing.is_empty() {
        return Selected::Continuous { in_flight };
    }
    warn!(
        missing = missing.join(", "),
        "Running the capped polling strategy: continuous polling needs all its requirements"
    );
    capped
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
    use std::num::NonZeroU64;

    use super::*;

    struct SelectCase {
        granularity: CompletionGranularity,
        budget_set: bool,
        in_flight_set: bool,
        expected_continuous: bool,
    }

    #[rstest::rstest]
    #[case::all_requirements(SelectCase { granularity: CompletionGranularity::Group, budget_set: true, in_flight_set: true, expected_continuous: true })]
    #[case::poll_granularity(SelectCase { granularity: CompletionGranularity::Poll, budget_set: true, in_flight_set: true, expected_continuous: false })]
    #[case::no_budget(SelectCase { granularity: CompletionGranularity::Group, budget_set: false, in_flight_set: true, expected_continuous: false })]
    #[case::no_in_flight_limit(SelectCase { granularity: CompletionGranularity::Group, budget_set: true, in_flight_set: false, expected_continuous: false })]
    fn continuous_polling_runs_only_with_all_its_requirements(#[case] case: SelectCase) {
        let budget = if case.budget_set {
            BudgetLimits::new(NonZeroU64::new(100), None, 0.8).unwrap()
        } else {
            BudgetLimits::unset()
        };
        let in_flight = if case.in_flight_set {
            ChargeLimit::new(NonZeroU64::new(1_000), None)
        } else {
            ChargeLimit::unset()
        };

        let selected = select(Polling::Continuous, case.granularity, &budget, in_flight, 4);

        let expected = if case.expected_continuous {
            Selected::Continuous { in_flight }
        } else {
            Selected::Capped {
                max_in_flight_polls: 4,
            }
        };
        assert_eq!(selected, expected);
    }

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
