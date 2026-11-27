use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{Charge, TopicPartition};
use metrics::{counter, gauge, histogram};
use tracing::info;

use super::{Admission, HandedOut, Pause};
use crate::partition_budget::BudgetLimits;

const PAUSED_PARTITIONS: &str = "ingestion_consumer_budget_paused_partitions";
const PAUSES: &str = "ingestion_consumer_budget_pauses_total";
const PAUSE_SECONDS: &str = "ingestion_consumer_budget_pause_seconds";

type Clock = Arc<dyn Fn() -> Instant + Send + Sync>;

pub(crate) struct PartitionBudget {
    limits: BudgetLimits,
    paused: Mutex<HashMap<TopicPartition, Instant>>,
    clock: Clock,
}

impl PartitionBudget {
    pub(super) fn new(limits: BudgetLimits) -> Self {
        Self::with_clock(limits, Arc::new(Instant::now))
    }

    fn with_clock(limits: BudgetLimits, clock: Clock) -> Self {
        gauge!(PAUSED_PARTITIONS).set(0.0);
        Self {
            limits,
            paused: Mutex::new(HashMap::new()),
            clock,
        }
    }
}

impl Admission for PartitionBudget {
    fn charged(&self, topic_partition: &TopicPartition, uncommitted: Charge) -> Option<Pause> {
        if !self.limits.pauses(uncommitted) {
            return None;
        }
        let mut paused = self.paused.lock().unwrap();
        match paused.entry(topic_partition.clone()) {
            Entry::Occupied(_) => return None,
            Entry::Vacant(entry) => {
                entry.insert((self.clock)());
            }
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
            if !self.limits.resumes(uncommitted) {
                continue;
            }
            if let Some(paused_at) = paused.remove(topic_partition) {
                record_pause(paused_at, (self.clock)());
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
            if let Some(paused_at) = paused.remove(topic_partition) {
                record_pause(paused_at, (self.clock)());
            }
        }
        gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
    }
}

fn record_pause(paused_at: Instant, ended_at: Instant) {
    histogram!(PAUSE_SECONDS).record(ended_at.saturating_duration_since(paused_at).as_secs_f64());
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
    use std::time::Duration;

    use common_kafka_consumer::{Held, Offset};
    use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};

    use super::*;

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    fn p1() -> TopicPartition {
        TopicPartition::new("events", 1)
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

    fn handed_out(remaining_events: u64) -> HandedOut {
        HandedOut {
            offset: Offset(1),
            remaining: Held {
                offsets: remaining_events as usize,
                charge: events(remaining_events),
            },
        }
    }

    fn hand_out_leaving(budget: &PartitionBudget, remaining_events: u64) -> Vec<TopicPartition> {
        budget.handed_out(&HashMap::from([(p0(), handed_out(remaining_events))]))
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

    #[derive(Debug, PartialEq)]
    struct Recorded {
        paused_partitions: f64,
        pauses: HashMap<String, u64>,
        pause_seconds: Vec<f64>,
    }

    fn recorded(snapshotter: &Snapshotter) -> Recorded {
        let mut recorded = Recorded {
            paused_partitions: f64::NAN,
            pauses: HashMap::new(),
            pause_seconds: Vec::new(),
        };
        for (key, _, _, value) in snapshotter.snapshot().into_vec() {
            match (key.key().name(), value) {
                (PAUSED_PARTITIONS, DebugValue::Gauge(value)) => {
                    recorded.paused_partitions = value.into_inner();
                }
                (PAUSE_SECONDS, DebugValue::Histogram(samples)) => {
                    recorded.pause_seconds = samples.iter().map(|s| s.into_inner()).collect();
                }
                (PAUSES, DebugValue::Counter(count)) => {
                    let partition = key
                        .key()
                        .labels()
                        .find(|label| label.key() == "partition")
                        .expect("a partition label")
                        .value()
                        .to_string();
                    recorded.pauses.insert(partition, count);
                }
                _ => {}
            }
        }
        recorded
    }

    #[test]
    fn the_metrics_follow_pauses_resumes_and_revokes() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        let now = Arc::new(Mutex::new(Instant::now()));
        let clock = Arc::clone(&now);
        let budget = PartitionBudget::with_clock(
            BudgetLimits::new(NonZeroU64::new(10), None, 0.8).expect("valid limits"),
            Arc::new(move || *clock.lock().unwrap()),
        );
        let advance = |seconds: u64| *now.lock().unwrap() += Duration::from_secs(seconds);

        budget.charged(&p0(), events(10));
        budget.charged(&p1(), events(10));
        advance(10);
        budget.charged(&p0(), events(12));
        assert_eq!(
            recorded(&snapshotter),
            Recorded {
                paused_partitions: 2.0,
                pauses: HashMap::from([("0".to_string(), 1), ("1".to_string(), 1)]),
                pause_seconds: Vec::new(),
            }
        );

        advance(30);
        let resume = budget.handed_out(&HashMap::from([
            (p0(), handed_out(0)),
            (p1(), handed_out(9)),
        ]));
        assert_eq!(resume, vec![p0()]);
        let after_resume = recorded(&snapshotter);
        assert_eq!(after_resume.paused_partitions, 1.0);
        assert_eq!(
            after_resume.pause_seconds,
            vec![40.0],
            "a charge while paused keeps the pause's start"
        );

        advance(60);
        budget.forget_partitions(&[p1()]);
        let after_revoke = recorded(&snapshotter);
        assert_eq!(after_revoke.paused_partitions, 0.0);
        assert_eq!(
            after_revoke.pause_seconds,
            vec![100.0],
            "a revoke ends the pause it interrupts"
        );
    }
}
