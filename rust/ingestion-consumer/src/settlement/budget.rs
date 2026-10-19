use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

use common_kafka_consumer::{Charge, TopicPartition};
use metrics::{counter, gauge};
use tracing::info;

use super::{Admission, HandedOut, Pause};
use crate::partition_budget::BudgetLimits;

const PAUSED_PARTITIONS: &str = "ingestion_consumer_budget_paused_partitions";
const PAUSES: &str = "ingestion_consumer_budget_pauses_total";

pub(crate) struct PartitionBudget {
    limits: BudgetLimits,
    paused: Mutex<HashSet<TopicPartition>>,
}

impl PartitionBudget {
    pub(super) fn new(limits: BudgetLimits) -> Self {
        gauge!(PAUSED_PARTITIONS).set(0.0);
        Self {
            limits,
            paused: Mutex::new(HashSet::new()),
        }
    }
}

impl Admission for PartitionBudget {
    fn charged(&self, topic_partition: &TopicPartition, uncommitted: Charge) -> Option<Pause> {
        if !self.limits.pauses(uncommitted) {
            return None;
        }
        let mut paused = self.paused.lock().unwrap();
        if !paused.insert(topic_partition.clone()) {
            return None;
        }
        gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
        let topic: Arc<str> = Arc::from(topic_partition.topic.as_str());
        let partition: Arc<str> = Arc::from(topic_partition.partition.to_string());
        counter!(PAUSES, "topic" => topic, "partition" => partition).increment(1);
        log_transition(topic_partition, "pause", uncommitted);
        Some(Pause)
    }

    fn handed_out(&self, handed_out: &HashMap<TopicPartition, HandedOut>) -> Vec<TopicPartition> {
        let mut paused = self.paused.lock().unwrap();
        let mut resume = Vec::new();
        for (topic_partition, handed_out) in handed_out {
            let uncommitted = handed_out.remaining.charge;
            if paused.contains(topic_partition) && self.limits.resumes(uncommitted) {
                paused.remove(topic_partition);
                log_transition(topic_partition, "resume", uncommitted);
                resume.push(topic_partition.clone());
            }
        }
        if !resume.is_empty() {
            gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
        }
        resume
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
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

    use common_kafka_consumer::{Held, Offset};

    use super::*;

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    fn events(events: u64) -> Charge {
        Charge { events, bytes: 0 }
    }

    fn budget_of_10_events_resuming_under_8() -> PartitionBudget {
        PartitionBudget::new(
            BudgetLimits::new(NonZeroU64::new(10), None, 0.8).expect("valid limits"),
        )
    }

    #[rstest::rstest]
    #[case::below_the_limit(9, None)]
    #[case::at_the_limit(10, Some(Pause))]
    fn a_charge_pauses_a_partition_that_reaches_its_limit(
        #[case] uncommitted: u64,
        #[case] expected: Option<Pause>,
    ) {
        assert_eq!(
            budget_of_10_events_resuming_under_8().charged(&p0(), events(uncommitted)),
            expected
        );
    }

    #[test]
    fn a_paused_partition_pauses_once() {
        let budget = budget_of_10_events_resuming_under_8();
        assert_eq!(budget.charged(&p0(), events(10)), Some(Pause));

        assert_eq!(budget.charged(&p0(), events(12)), None);
    }

    fn hand_out_leaving(budget: &PartitionBudget, remaining_events: u64) -> Vec<TopicPartition> {
        budget.handed_out(&HashMap::from([(
            p0(),
            HandedOut {
                offset: Offset(1),
                remaining: Held {
                    offsets: remaining_events as usize,
                    charge: events(remaining_events),
                },
            },
        )]))
    }

    #[rstest::rstest]
    #[case::above_the_watermark(9, false)]
    #[case::at_the_watermark(8, false)]
    #[case::under_the_watermark(7, true)]
    fn a_hand_out_resumes_a_paused_partition_under_the_watermark(
        #[case] remaining: u64,
        #[case] expected_resume: bool,
    ) {
        let budget = budget_of_10_events_resuming_under_8();
        budget.charged(&p0(), events(10));

        assert_eq!(
            hand_out_leaving(&budget, remaining).contains(&p0()),
            expected_resume
        );
    }

    #[test]
    fn a_hand_out_never_resumes_a_partition_that_is_not_paused() {
        let budget = budget_of_10_events_resuming_under_8();

        assert!(hand_out_leaving(&budget, 0).is_empty());
    }

    #[test]
    fn a_resumed_partition_pauses_again_at_its_limit() {
        let budget = budget_of_10_events_resuming_under_8();
        budget.charged(&p0(), events(10));
        hand_out_leaving(&budget, 0);

        assert_eq!(budget.charged(&p0(), events(10)), Some(Pause));
    }

    #[test]
    fn a_forgotten_partition_starts_unpaused() {
        let budget = budget_of_10_events_resuming_under_8();
        budget.charged(&p0(), events(10));

        budget.forget_partitions(&[p0()]);

        assert_eq!(budget.charged(&p0(), events(10)), Some(Pause));
    }
}
