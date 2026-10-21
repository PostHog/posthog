//! How the consumer loop turns what it receives into what it does next. The
//! consumer owns the Kafka client and the batcher outputs, hands each event to
//! the polling strategy, and carries out the [`Step`]s the strategy returns.

mod capped;
mod collector;
mod continuous;
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

use capped::CappedPolling;
use collector::Collector;
pub(crate) use collector::PollLimits;
use continuous::ContinuousPolling;
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

pub(crate) enum PollingStrategy {
    Capped(Box<CappedPolling>),
    Continuous(Box<ContinuousPolling>),
}

impl PollingStrategy {
    pub(crate) fn new(selected: Selected, parts: Parts) -> Self {
        match selected {
            Selected::Capped {
                max_in_flight_polls,
            } => Self::Capped(Box::new(CappedPolling::new(parts, max_in_flight_polls))),
            Selected::Continuous { in_flight } => {
                Self::Continuous(Box::new(ContinuousPolling::new(parts, in_flight)))
            }
        }
    }

    pub(crate) fn reading(&mut self) -> bool {
        match self {
            Self::Capped(capped) => capped.reading(),
            Self::Continuous(continuous) => continuous.reading(),
        }
    }

    pub(crate) fn deadline(&self) -> Option<Instant> {
        match self {
            Self::Capped(capped) => capped.deadline(),
            Self::Continuous(continuous) => continuous.deadline(),
        }
    }

    pub(crate) fn received(&mut self, message: &impl Message, now: Instant) {
        match self {
            Self::Capped(capped) => capped.received(message, now),
            Self::Continuous(continuous) => continuous.received(message, now),
        }
    }

    pub(crate) fn completed(&mut self, completion: &GroupCompletion) -> anyhow::Result<()> {
        match self {
            Self::Capped(capped) => capped.completed(completion),
            Self::Continuous(continuous) => continuous.completed(completion),
        }
    }

    pub(crate) fn ticked(&mut self) {
        match self {
            Self::Capped(capped) => capped.ticked(),
            Self::Continuous(continuous) => continuous.ticked(),
        }
    }

    /// Every message received before the revoke belongs to the old
    /// assignment: the batcher purges it, or Kafka delivers it again from the
    /// last commit.
    pub(crate) fn revoked(&mut self, topic_partitions: &[TopicPartition]) {
        match self {
            Self::Capped(capped) => capped.revoked(topic_partitions),
            Self::Continuous(continuous) => continuous.revoked(topic_partitions),
        }
    }

    /// The poll in progress is not charged yet, so it is dropped and replays
    /// from the last commit.
    pub(crate) fn shutdown(&mut self) {
        match self {
            Self::Capped(capped) => capped.shutdown(),
            Self::Continuous(continuous) => continuous.shutdown(),
        }
    }

    pub(crate) fn submitted(&mut self, poll: InFlightPoll) {
        match self {
            Self::Capped(capped) => capped.submitted(poll),
            Self::Continuous(continuous) => continuous.submitted(poll),
        }
    }

    pub(crate) fn next_step(&mut self, now: Instant) -> Option<Step> {
        match self {
            Self::Capped(capped) => capped.next_step(now),
            Self::Continuous(continuous) => continuous.next_step(now),
        }
    }
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

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::num::NonZeroU64;
    use std::time::Duration;

    use common_kafka_consumer::{Offset, Partition, TopicOffsetLedger};

    use super::collector::tests::message;
    use super::*;
    use crate::settlement::GroupSettlement;

    const BATCH_TIMEOUT: Duration = Duration::from_millis(500);

    struct Harness {
        poller: PollingStrategy,
        settlement: Arc<dyn Settlement>,
        ledger: Arc<TopicOffsetLedger>,
        now: Instant,
    }

    impl Harness {
        fn new(selected: Selected) -> Self {
            let ledger = Arc::new(TopicOffsetLedger::new());
            let settlement: Arc<dyn Settlement> = Arc::new(GroupSettlement::new(
                Arc::clone(&ledger),
                Duration::ZERO,
                BudgetLimits::unset(),
            ));
            let limits = PollLimits {
                batch_size: 100,
                batch_size_bytes: 0,
                batch_timeout: BATCH_TIMEOUT,
            };
            Self {
                poller: PollingStrategy::new(
                    selected,
                    Parts {
                        limits,
                        settlement: Arc::clone(&settlement),
                        group_id: "test".to_string(),
                        debug_recorder: None,
                    },
                ),
                settlement,
                ledger,
                now: Instant::now(),
            }
        }

        fn capped(max_in_flight_polls: usize) -> Self {
            Self::new(Selected::Capped {
                max_in_flight_polls,
            })
        }

        fn continuous(in_flight_events: u64) -> Self {
            Self::new(Selected::Continuous {
                in_flight: ChargeLimit::new(NonZeroU64::new(in_flight_events), None),
            })
        }

        fn receive(&mut self, partition: i32, offsets: &[i64]) {
            for &offset in offsets {
                self.poller
                    .received(&message(partition, offset, 10), self.now);
            }
        }

        fn after_the_batch_timeout(&mut self) {
            self.now += BATCH_TIMEOUT;
        }

        fn step(&mut self) -> Option<Step> {
            self.poller.next_step(self.now)
        }

        fn submit(&mut self) -> HashMap<TopicPartition, (i64, i64)> {
            let Some(Step::Submit(collected)) = self.step() else {
                panic!("expected a poll to submit");
            };
            let CollectedBatch {
                accumulator,
                mut partitions,
                ..
            } = collected;
            let mut uncommitted = HashMap::new();
            for (topic_partition, deliveries) in &mut partitions {
                deliveries.generation = self.ledger.generation(topic_partition);
                let charged = self
                    .settlement
                    .charge(topic_partition, deliveries.generation, &deliveries.charges)
                    .expect("the ledger accepts the charge");
                uncommitted.insert(topic_partition.clone(), charged.uncommitted);
            }
            let spans = partitions
                .iter()
                .map(|(topic_partition, deliveries)| {
                    (
                        topic_partition.clone(),
                        (deliveries.span.first, deliveries.span.last),
                    )
                })
                .collect();
            self.poller.submitted(InFlightPoll {
                poll_id: "poll".to_string(),
                assignment_epoch: 1,
                partitions,
                uncommitted,
                message_count: accumulator.message_count() as u32,
                covered: 0,
                accepted: 0,
                dispatched_at: std::time::Instant::now(),
            });
            spans
        }

        fn complete(&mut self, partition: i32, offsets: &[i64]) {
            self.poller
                .completed(&GroupCompletion {
                    partition: Partition(partition),
                    assignment_epoch: 1,
                    offsets: offsets.iter().map(|&offset| Offset(offset)).collect(),
                    accepted: offsets.len() as u32,
                })
                .expect("the completion applies");
        }

        fn commit(&mut self) -> HashMap<TopicPartition, Offset> {
            match self.step() {
                Some(Step::Commit(commit)) => commit.offsets,
                _ => panic!("expected a commit"),
            }
        }
    }

    fn p(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    #[test]
    fn the_capped_strategy_stops_reading_at_its_cap_until_the_oldest_poll_is_covered() {
        let mut harness = Harness::capped(1);
        assert!(harness.poller.reading());

        harness.receive(0, &[0, 1]);
        assert!(harness.step().is_none(), "the poll is still collecting");
        harness.after_the_batch_timeout();
        harness.submit();
        assert!(!harness.poller.reading());

        harness.complete(0, &[0, 1]);
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(2))]));
        assert!(harness.poller.reading());
    }

    #[test]
    fn the_continuous_strategy_stops_reading_one_poll_past_its_limit_until_a_commit() {
        let mut harness = Harness::continuous(1);

        harness.receive(0, &[0, 1]);
        assert!(
            harness.poller.reading(),
            "the poll in progress is not counted"
        );
        harness.after_the_batch_timeout();
        assert_eq!(harness.submit(), HashMap::from([(p(0), (0, 1))]));
        assert!(!harness.poller.reading());

        harness.complete(0, &[0, 1]);
        assert!(
            !harness.poller.reading(),
            "a completion frees no room before its commit"
        );
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(2))]));
        assert!(harness.poller.reading());
    }

    #[test]
    fn a_revoke_removes_the_partitions_messages_received_before_it() {
        let mut harness = Harness::continuous(1_000);
        harness.receive(0, &[10, 11]);
        harness.receive(1, &[20]);

        harness.poller.revoked(&[p(0)]);
        harness.receive(0, &[10]);
        harness.after_the_batch_timeout();

        assert_eq!(
            harness.submit(),
            HashMap::from([(p(0), (10, 10)), (p(1), (20, 20))]),
            "the redelivery after the revoke stays"
        );
    }

    #[test]
    fn shutdown_drops_the_poll_in_progress_and_stops_once_in_flight_work_drains() {
        let mut harness = Harness::continuous(1_000);
        harness.receive(0, &[0]);
        harness.after_the_batch_timeout();
        harness.submit();
        harness.receive(0, &[1]);

        harness.poller.shutdown();
        assert!(!harness.poller.reading());
        assert_eq!(harness.poller.deadline(), None);
        assert!(harness.step().is_none(), "offset 0 is still in flight");

        harness.complete(0, &[0]);
        assert_eq!(harness.commit(), HashMap::from([(p(0), Offset(1))]));
        assert!(matches!(harness.step(), Some(Step::Stop)));
    }

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
}
