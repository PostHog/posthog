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

    /// Only a commit lowers a partition's uncommitted charge, so only the
    /// partitions it covers can resume.
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

    use common_kafka_consumer::TopicOffsetLedger;

    use super::*;
    use crate::commit_pacer::CommitPacer;

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    fn events(events: u64) -> Charge {
        Charge { events, bytes: 0 }
    }

    fn budget_of_10_events_resuming_at_8() -> PartitionBudget {
        PartitionBudget::new(
            Uncommitted::new(Arc::new(TopicOffsetLedger::new()), CommitPacer::immediate()),
            BudgetLimits::new(NonZeroU64::new(10), None, 0.8).expect("valid limits"),
        )
    }

    fn charge(budget: &PartitionBudget, offset: i64, charge: Charge) -> Option<Pause> {
        budget
            .charge(&p0(), 0, &[(Offset(offset), charge)])
            .expect("the ledger accepts the charge")
    }

    fn commit(budget: &PartitionBudget, offsets: &[i64]) -> Vec<TopicPartition> {
        budget
            .settled(&p0(), 0, offsets.iter().map(|&o| Offset(o)))
            .expect("the ledger settles");
        budget.take_due(Instant::now()).expect("due").resume
    }

    #[test]
    fn a_paused_partition_pauses_once() {
        let budget = budget_of_10_events_resuming_at_8();
        assert_eq!(charge(&budget, 0, events(10)), Some(Pause));

        assert_eq!(charge(&budget, 1, events(2)), None);
    }

    struct Committed {
        remaining: Charge,
        expected_resume: bool,
    }

    #[rstest::rstest]
    #[case::still_above_the_watermark(Committed { remaining: events(9), expected_resume: false })]
    #[case::at_the_watermark(Committed { remaining: events(8), expected_resume: true })]
    fn a_commit_resumes_a_partition_it_brings_under_the_watermark(#[case] committed: Committed) {
        let budget = budget_of_10_events_resuming_at_8();
        charge(&budget, 0, events(10));
        charge(&budget, 1, committed.remaining);

        let resume = commit(&budget, &[0]);

        assert_eq!(resume.contains(&p0()), committed.expected_resume);
    }

    #[test]
    fn a_resumed_partition_pauses_again_at_its_limit() {
        let budget = budget_of_10_events_resuming_at_8();
        charge(&budget, 0, events(10));
        assert_eq!(commit(&budget, &[0]), vec![p0()]);

        assert_eq!(charge(&budget, 1, events(10)), Some(Pause));
    }

    #[test]
    fn a_forgotten_partition_starts_unpaused() {
        let budget = budget_of_10_events_resuming_at_8();
        charge(&budget, 0, events(10));

        budget.forget_partitions(&[p0()]);

        assert_eq!(
            budget
                .charge(&p0(), 1, &[(Offset(0), events(10))])
                .expect("the new generation charges"),
            Some(Pause)
        );
    }
}
