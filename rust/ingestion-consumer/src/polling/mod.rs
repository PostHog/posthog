//! How the consumer loop turns what it receives into what it does next. The
//! consumer owns the Kafka client and the batcher outputs, hands each event to
//! the polling strategy, and carries out the [`Step`]s the strategy returns.

mod capped;
mod collector;
mod continuous;
#[cfg(test)]
mod harness;
mod poll;

use std::sync::Arc;

use common_kafka_consumer::{GroupCompletion, TopicPartition};
use metrics::counter;
use rdkafka::message::Message;
use tokio::time::Instant;
use tracing::{info, warn};

use crate::charge_limit::ChargeLimit;
use crate::config::{CompletionGranularity, Polling};
use crate::debug_recorder::DebugRecorder;
use crate::partition_budget::BudgetLimits;
use crate::settlement::{Commit, Settlement};

pub(crate) use capped::CappedPolling;
use collector::Collector;
pub(crate) use collector::PollLimits;
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
    /// Shutdown drained the in-flight work.
    Stop,
    Fail(anyhow::Error),
}

pub(crate) struct Parts {
    pub(crate) limits: PollLimits,
    pub(crate) settlement: Arc<dyn Settlement>,
    pub(crate) group_id: String,
    pub(crate) debug_recorder: Option<Arc<DebugRecorder>>,
}

pub(crate) trait PollingStrategy {
    fn reading(&mut self) -> bool;

    fn deadline(&self) -> Option<Instant>;

    fn received<M: Message>(&mut self, message: &M, now: Instant);

    fn completed(&mut self, completion: &GroupCompletion) -> anyhow::Result<()>;

    fn ticked(&mut self);

    /// Every message received before the revoke belongs to the old
    /// assignment: the batcher purges it, or Kafka delivers it again from the
    /// last commit.
    fn revoked(&mut self, topic_partitions: &[TopicPartition]);

    /// The poll in progress is not charged yet, so it is dropped and replays
    /// from the last commit.
    fn shutdown(&mut self);

    fn submitted(&mut self, poll: InFlightPoll);

    fn next_step(&mut self, now: Instant) -> Option<Step>;
}

fn report_revoked(stripped: u64) {
    if stripped > 0 {
        counter!("ingestion_consumer_polls_dropped_on_revoke_total").increment(stripped);
        info!(stripped, "Removed revoked partitions' messages");
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Selected {
    Capped { max_in_flight_polls: usize },
    Continuous { in_flight: ChargeLimit },
}

/// Continuous polling needs `group` granularity, because at `poll` only a
/// retired poll settles, and continuous polling retires no poll. It needs a
/// partition budget and an in-flight limit, because it has no in-flight poll
/// cap. Each needs both axes, because one axis alone leaves the other
/// unbounded: a message with no key, value or headers charges zero bytes.
/// Without all three the capped strategy runs, so a lane rolled back to `poll` needs no
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
        (
            !budget.sets_both_axes(),
            "a partition budget on events and bytes",
        ),
        (
            !in_flight.sets_both_axes(),
            "an in-flight limit on events and bytes",
        ),
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

#[cfg(test)]
mod tests {
    use std::num::NonZeroU64;

    use super::*;

    #[derive(Clone, Copy)]
    enum Axes {
        Neither,
        Events,
        Bytes,
        Both,
    }

    impl Axes {
        fn limits(self) -> (Option<NonZeroU64>, Option<NonZeroU64>) {
            let (events, bytes) = match self {
                Axes::Neither => (0, 0),
                Axes::Events => (100, 0),
                Axes::Bytes => (0, 100_000),
                Axes::Both => (100, 100_000),
            };
            (NonZeroU64::new(events), NonZeroU64::new(bytes))
        }
    }

    struct SelectCase {
        granularity: CompletionGranularity,
        budget: Axes,
        in_flight: Axes,
        expected_continuous: bool,
    }

    #[rstest::rstest]
    #[case::all_requirements(SelectCase { granularity: CompletionGranularity::Group, budget: Axes::Both, in_flight: Axes::Both, expected_continuous: true })]
    #[case::poll_granularity(SelectCase { granularity: CompletionGranularity::Poll, budget: Axes::Both, in_flight: Axes::Both, expected_continuous: false })]
    #[case::no_budget(SelectCase { granularity: CompletionGranularity::Group, budget: Axes::Neither, in_flight: Axes::Both, expected_continuous: false })]
    #[case::event_only_budget(SelectCase { granularity: CompletionGranularity::Group, budget: Axes::Events, in_flight: Axes::Both, expected_continuous: false })]
    #[case::byte_only_budget(SelectCase { granularity: CompletionGranularity::Group, budget: Axes::Bytes, in_flight: Axes::Both, expected_continuous: false })]
    #[case::no_in_flight_limit(SelectCase { granularity: CompletionGranularity::Group, budget: Axes::Both, in_flight: Axes::Neither, expected_continuous: false })]
    #[case::event_only_in_flight_limit(SelectCase { granularity: CompletionGranularity::Group, budget: Axes::Both, in_flight: Axes::Events, expected_continuous: false })]
    #[case::byte_only_in_flight_limit(SelectCase { granularity: CompletionGranularity::Group, budget: Axes::Both, in_flight: Axes::Bytes, expected_continuous: false })]
    fn continuous_polling_runs_only_with_all_its_requirements(#[case] case: SelectCase) {
        let (events, bytes) = case.budget.limits();
        let budget = BudgetLimits::new(events, bytes, 0.8).unwrap();
        let (events, bytes) = case.in_flight.limits();
        let in_flight = ChargeLimit::new(events, bytes);

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
}
