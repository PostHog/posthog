//! Replay exposure per partition: a partition whose uncommitted work reaches
//! its budget pauses until commits bring it under the low watermark.

use std::collections::HashSet;
use std::num::NonZeroU64;
use std::sync::{Arc, Mutex};

use common_kafka_consumer::{Charge, TopicPartition};
use metrics::{counter, gauge};

const PAUSED_PARTITIONS: &str = "ingestion_consumer_budget_paused_partitions";
const PAUSES: &str = "ingestion_consumer_budget_pauses_total";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transition {
    Pause,
    Resume,
}

#[derive(Debug, Clone, Copy)]
struct Threshold {
    events: Option<u64>,
    bytes: Option<u64>,
}

impl Threshold {
    fn reached(&self, charge: Charge) -> bool {
        self.events.is_some_and(|limit| charge.events >= limit)
            || self.bytes.is_some_and(|limit| charge.bytes >= limit)
    }

    fn within(&self, charge: Charge) -> bool {
        self.events.is_none_or(|limit| charge.events <= limit)
            && self.bytes.is_none_or(|limit| charge.bytes <= limit)
    }

    fn scaled(&self, fraction: f64) -> Self {
        let scale = |limit: u64| (limit as f64 * fraction) as u64;
        Self {
            events: self.events.map(scale),
            bytes: self.bytes.map(scale),
        }
    }
}

#[derive(Debug, Clone, Copy)]
struct Limits {
    pause_at: Threshold,
    resume_at: Threshold,
}

pub struct PartitionBudget {
    limits: Option<Limits>,
    paused: Mutex<HashSet<TopicPartition>>,
}

impl PartitionBudget {
    pub fn unset() -> Self {
        gauge!(PAUSED_PARTITIONS).set(0.0);
        Self {
            limits: None,
            paused: Mutex::new(HashSet::new()),
        }
    }

    /// `low_watermark` is the fraction of the budget a paused partition must
    /// be back under, on every set axis, to resume. With neither axis set
    /// the budget is unset.
    pub fn new(
        events: Option<NonZeroU64>,
        bytes: Option<NonZeroU64>,
        low_watermark: f64,
    ) -> Result<Self, String> {
        if !(low_watermark > 0.0 && low_watermark <= 1.0) {
            return Err(format!(
                "the low watermark must be above 0 and at most 1, got {low_watermark}"
            ));
        }
        if events.is_none() && bytes.is_none() {
            return Ok(Self::unset());
        }
        let pause_at = Threshold {
            events: events.map(NonZeroU64::get),
            bytes: bytes.map(NonZeroU64::get),
        };
        let budget = Self::unset();
        Ok(Self {
            limits: Some(Limits {
                pause_at,
                resume_at: pause_at.scaled(low_watermark),
            }),
            ..budget
        })
    }

    pub fn is_set(&self) -> bool {
        self.limits.is_some()
    }

    /// After a poll charged the partition or a commit released some of it.
    pub fn observe(
        &self,
        topic_partition: &TopicPartition,
        uncommitted: Charge,
    ) -> Option<Transition> {
        let limits = self.limits?;
        let mut paused = self.paused.lock().unwrap();
        let transition = if paused.contains(topic_partition) {
            if !limits.resume_at.within(uncommitted) {
                return None;
            }
            paused.remove(topic_partition);
            Transition::Resume
        } else {
            if !limits.pause_at.reached(uncommitted) {
                return None;
            }
            paused.insert(topic_partition.clone());
            let topic: Arc<str> = Arc::from(topic_partition.topic.as_str());
            let partition: Arc<str> = Arc::from(topic_partition.partition.to_string());
            counter!(PAUSES, "topic" => topic, "partition" => partition).increment(1);
            Transition::Pause
        };
        gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
        Some(transition)
    }

    /// The partition left the assignment, or came back with its pause flag
    /// cleared by the client.
    pub fn forget(&self, topic_partition: &TopicPartition) {
        let mut paused = self.paused.lock().unwrap();
        if paused.remove(topic_partition) {
            gauge!(PAUSED_PARTITIONS).set(paused.len() as f64);
        }
    }
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;

    fn budget(events: u64, bytes: u64, low_watermark: f64) -> PartitionBudget {
        PartitionBudget::new(
            NonZeroU64::new(events),
            NonZeroU64::new(bytes),
            low_watermark,
        )
        .expect("a valid budget")
    }

    fn charge(events: u64, bytes: u64) -> Charge {
        Charge { events, bytes }
    }

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    struct Observed {
        uncommitted: Charge,
        expected: Option<Transition>,
    }

    #[rstest]
    #[case::below_both_limits(charge(9, 999), None)]
    #[case::at_the_event_limit(charge(10, 0), Some(Transition::Pause))]
    #[case::at_the_byte_limit(charge(0, 1000), Some(Transition::Pause))]
    fn a_partition_pauses_when_either_axis_reaches_its_limit(
        #[case] uncommitted: Charge,
        #[case] expected: Option<Transition>,
    ) {
        assert_eq!(budget(10, 1000, 0.8).observe(&p0(), uncommitted), expected);
    }

    #[rstest]
    #[case::still_above_the_limit(Observed { uncommitted: charge(10, 0), expected: None })]
    #[case::between_the_watermark_and_the_limit(Observed { uncommitted: charge(9, 0), expected: None })]
    #[case::one_axis_still_above_the_watermark(Observed { uncommitted: charge(8, 801), expected: None })]
    #[case::under_the_watermark_on_both_axes(Observed { uncommitted: charge(8, 800), expected: Some(Transition::Resume) })]
    fn a_paused_partition_resumes_under_the_watermark_on_every_axis(#[case] observed: Observed) {
        let budget = budget(10, 1000, 0.8);
        assert_eq!(
            budget.observe(&p0(), charge(10, 0)),
            Some(Transition::Pause)
        );

        assert_eq!(
            budget.observe(&p0(), observed.uncommitted),
            observed.expected
        );
    }

    #[test]
    fn a_paused_partition_pauses_once() {
        let budget = budget(10, 0, 0.8);
        assert_eq!(
            budget.observe(&p0(), charge(10, 0)),
            Some(Transition::Pause)
        );

        assert_eq!(budget.observe(&p0(), charge(12, 0)), None);
    }

    #[test]
    fn a_forgotten_partition_starts_unpaused() {
        let budget = budget(10, 0, 0.8);
        budget.observe(&p0(), charge(10, 0));

        budget.forget(&p0());

        assert_eq!(
            budget.observe(&p0(), charge(10, 0)),
            Some(Transition::Pause)
        );
    }

    #[test]
    fn an_unset_budget_never_pauses() {
        let budget = PartitionBudget::new(None, None, 0.8).expect("unset is valid");
        assert!(!budget.is_set());
        assert_eq!(budget.observe(&p0(), charge(u64::MAX, u64::MAX)), None);
    }

    #[rstest]
    #[case::zero(0.0)]
    #[case::above_one(1.5)]
    fn a_watermark_outside_the_unit_interval_is_rejected(#[case] low_watermark: f64) {
        assert!(PartitionBudget::new(NonZeroU64::new(10), None, low_watermark).is_err());
    }
}
