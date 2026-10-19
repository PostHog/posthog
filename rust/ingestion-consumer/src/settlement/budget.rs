use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{Charge, Offset, Rejection, TopicPartition};
use metrics::{counter, gauge};
use tracing::info;

use super::uncommitted::Uncommitted;
use super::{Accounting, Admission};
use crate::partition_budget::BudgetLimits;

const PAUSED_PARTITIONS: &str = "ingestion_consumer_budget_paused_partitions";
const PAUSES: &str = "ingestion_consumer_budget_pauses_total";

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Pause;

pub(crate) struct Commit {
    pub(crate) offsets: HashMap<TopicPartition, Offset>,
    pub(crate) resume: Vec<TopicPartition>,
}

impl Commit {
    pub(super) fn without_resumes(offsets: HashMap<TopicPartition, Offset>) -> Self {
        Self {
            offsets,
            resume: Vec::new(),
        }
    }
}

pub(crate) struct PartitionBudget<A: Accounting = Uncommitted> {
    accounting: A,
    limits: BudgetLimits,
    paused: Mutex<HashSet<TopicPartition>>,
}

impl<A: Accounting> PartitionBudget<A> {
    pub(super) fn new(accounting: A, limits: BudgetLimits) -> Self {
        gauge!(PAUSED_PARTITIONS).set(0.0);
        Self {
            accounting,
            limits,
            paused: Mutex::new(HashSet::new()),
        }
    }

    fn commit(&self, offsets: HashMap<TopicPartition, Offset>) -> Commit {
        let mut paused = self.paused.lock().unwrap();
        let mut resume = Vec::new();
        for topic_partition in offsets.keys() {
            if !paused.contains(topic_partition) {
                continue;
            }
            let uncommitted = self.accounting.held(topic_partition).charge;
            if self.limits.resumes(uncommitted) {
                paused.remove(topic_partition);
                log_transition(topic_partition, "resume", uncommitted);
                resume.push(topic_partition.clone());
            }
        }
        if !resume.is_empty() {
            gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
        }
        Commit { offsets, resume }
    }
}

impl<A: Accounting> Admission for PartitionBudget<A> {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Option<Pause>, Rejection> {
        let uncommitted = self
            .accounting
            .charge(topic_partition, generation, charges)?;
        if !self.limits.pauses(uncommitted.charge) {
            return Ok(None);
        }
        let mut paused = self.paused.lock().unwrap();
        if !paused.insert(topic_partition.clone()) {
            return Ok(None);
        }
        gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
        let topic: Arc<str> = Arc::from(topic_partition.topic.as_str());
        let partition: Arc<str> = Arc::from(topic_partition.partition.to_string());
        counter!(PAUSES, "topic" => topic, "partition" => partition).increment(1);
        log_transition(topic_partition, "pause", uncommitted.charge);
        Ok(Some(Pause))
    }

    fn settled(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<Option<Offset>, Rejection> {
        self.accounting
            .settled(topic_partition, generation, offsets)
    }

    fn take_due(&self, now: Instant) -> Option<Commit> {
        let offsets = self.accounting.take_due(now)?;
        Some(self.commit(offsets))
    }

    fn take_all(&self) -> Option<Commit> {
        let offsets = self.accounting.take_all()?;
        Some(self.commit(offsets))
    }

    fn paused(&self) -> Vec<TopicPartition> {
        self.paused.lock().unwrap().iter().cloned().collect()
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.accounting.forget_partitions(topic_partitions);
        let mut paused = self.paused.lock().unwrap();
        for topic_partition in topic_partitions {
            paused.remove(topic_partition);
        }
        gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
    }
}

fn log_transition(topic_partition: &TopicPartition, transition: &str, uncommitted: Charge) {
    info!(
        topic = %topic_partition.topic,
        partition = topic_partition.partition,
        uncommitted_events = uncommitted.events,
        uncommitted_bytes = uncommitted.bytes,
        transition,
        "Partition budget"
    );
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU64;

    use common_kafka_consumer::Held;

    use super::super::fakes::FakeAccounting;
    use super::*;

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    fn p1() -> TopicPartition {
        TopicPartition::new("events", 1)
    }

    fn uncommitted_events(events: u64) -> Held {
        Held {
            offsets: events as usize,
            charge: Charge { events, bytes: 0 },
        }
    }

    fn budget_of_10_events_resuming_at_8() -> PartitionBudget<FakeAccounting> {
        PartitionBudget::new(
            FakeAccounting::default(),
            BudgetLimits::new(NonZeroU64::new(10), None, 0.8).expect("valid limits"),
        )
    }

    fn charge_reaching(
        budget: &PartitionBudget<FakeAccounting>,
        topic_partition: &TopicPartition,
        uncommitted: u64,
    ) -> Option<Pause> {
        budget
            .accounting
            .charge_returns(Ok(uncommitted_events(uncommitted)));
        budget
            .charge(topic_partition, 0, &[])
            .expect("the accounting accepts the charge")
    }

    fn hand_out_leaving(
        budget: &PartitionBudget<FakeAccounting>,
        topic_partition: &TopicPartition,
        remaining: u64,
    ) -> Commit {
        budget
            .accounting
            .take_hands_out(HashMap::from([(topic_partition.clone(), Offset(1))]));
        budget
            .accounting
            .holds(topic_partition, uncommitted_events(remaining));
        budget
            .take_due(Instant::now())
            .expect("the accounting hands it out")
    }

    #[rstest::rstest]
    #[case::below_the_limit(9, None)]
    #[case::at_the_limit(10, Some(Pause))]
    fn a_charge_pauses_a_partition_that_reaches_its_limit(
        #[case] uncommitted: u64,
        #[case] expected: Option<Pause>,
    ) {
        assert_eq!(
            charge_reaching(&budget_of_10_events_resuming_at_8(), &p0(), uncommitted),
            expected
        );
    }

    #[test]
    fn a_paused_partition_pauses_once() {
        let budget = budget_of_10_events_resuming_at_8();
        assert_eq!(charge_reaching(&budget, &p0(), 10), Some(Pause));

        assert_eq!(charge_reaching(&budget, &p0(), 12), None);
    }

    #[test]
    fn a_rejected_charge_decides_nothing() {
        let budget = budget_of_10_events_resuming_at_8();
        let stale = Rejection::Stale {
            stamp: 0,
            generation: 1,
        };
        budget.accounting.charge_returns(Err(stale));

        assert_eq!(budget.charge(&p0(), 0, &[]), Err(stale));
        assert!(budget.paused().is_empty());
    }

    struct HandedOut {
        remaining: u64,
        expected_resume: bool,
    }

    #[rstest::rstest]
    #[case::above_the_watermark(HandedOut { remaining: 9, expected_resume: false })]
    #[case::at_the_watermark(HandedOut { remaining: 8, expected_resume: true })]
    fn a_hand_out_resumes_a_paused_partition_at_the_watermark(#[case] handed_out: HandedOut) {
        let budget = budget_of_10_events_resuming_at_8();
        charge_reaching(&budget, &p0(), 10);

        let commit = hand_out_leaving(&budget, &p0(), handed_out.remaining);

        assert_eq!(commit.resume.contains(&p0()), handed_out.expected_resume);
        assert_eq!(budget.paused().is_empty(), handed_out.expected_resume);
    }

    #[test]
    fn a_hand_out_never_resumes_a_partition_that_is_not_paused() {
        let budget = budget_of_10_events_resuming_at_8();

        assert!(hand_out_leaving(&budget, &p1(), 0).resume.is_empty());
    }

    #[test]
    fn take_all_resumes_like_take_due() {
        let budget = budget_of_10_events_resuming_at_8();
        charge_reaching(&budget, &p0(), 10);
        budget
            .accounting
            .take_hands_out(HashMap::from([(p0(), Offset(1))]));

        assert_eq!(budget.take_all().expect("handed out").resume, vec![p0()]);
    }

    #[test]
    fn a_resumed_partition_pauses_again_at_its_limit() {
        let budget = budget_of_10_events_resuming_at_8();
        charge_reaching(&budget, &p0(), 10);
        hand_out_leaving(&budget, &p0(), 0);

        assert_eq!(charge_reaching(&budget, &p0(), 10), Some(Pause));
    }

    #[test]
    fn a_forgotten_partition_starts_unpaused() {
        let budget = budget_of_10_events_resuming_at_8();
        charge_reaching(&budget, &p0(), 10);

        budget.forget_partitions(&[p0()]);

        assert_eq!(budget.accounting.forgotten(), vec![p0()]);
        assert!(budget.paused().is_empty());
        assert_eq!(charge_reaching(&budget, &p0(), 10), Some(Pause));
    }
}
