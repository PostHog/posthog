use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicOffsetLedger, TopicPartition};
use metrics::gauge;

use super::{Accounting, HandedOut};
use crate::commit_pacer::CommitPacer;

const UNCOMMITTED_OFFSETS: &str = "kafka_consumer_ledger_uncommitted_offsets";
const UNCOMMITTED_EVENTS: &str = "kafka_consumer_ledger_uncommitted_events";
const UNCOMMITTED_BYTES: &str = "kafka_consumer_ledger_uncommitted_bytes";

/// Counts each partition's charge from poll until the consumer makes the Kafka
/// commit call that covers it: first in the ledger's window, then in the pacer.
/// That call is asynchronous, and nothing here waits for Kafka to confirm it.
///
/// Every call runs on the consumer loop task, one at a time, so a move between
/// the ledger and the pacer never interleaves with a read of both.
pub(crate) struct Uncommitted {
    ledger: Arc<TopicOffsetLedger>,
    pacer: Mutex<CommitPacer>,
}

impl Uncommitted {
    pub(super) fn new(ledger: Arc<TopicOffsetLedger>, pacer: CommitPacer) -> Self {
        Self {
            ledger,
            pacer: Mutex::new(pacer),
        }
    }

    fn hand_out(&self, due: HashMap<TopicPartition, Offset>) -> HashMap<TopicPartition, HandedOut> {
        due.into_iter()
            .map(|(topic_partition, offset)| {
                let remaining = self.ledger.held(&topic_partition);
                publish(&topic_partition, remaining);
                (topic_partition, HandedOut { offset, remaining })
            })
            .collect()
    }
}

impl Accounting for Uncommitted {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Held, Rejection> {
        let held = self
            .ledger
            .charge(topic_partition, generation, charges.iter().copied())?;
        let uncommitted = held + self.pacer.lock().unwrap().pending(topic_partition);
        publish(topic_partition, uncommitted);
        Ok(uncommitted)
    }

    fn settled(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<Option<Offset>, Rejection> {
        let frontier = self.ledger.settle(topic_partition, generation, offsets)?;
        if frontier.is_some() {
            if let Some(taken) = self.ledger.take_frontier(topic_partition) {
                self.pacer
                    .lock()
                    .unwrap()
                    .advance_frontier(topic_partition, taken);
            }
        }
        Ok(frontier)
    }

    fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, HandedOut>> {
        let due = self.pacer.lock().unwrap().take_due(now)?;
        Some(self.hand_out(due))
    }

    fn take_all(&self) -> Option<HashMap<TopicPartition, HandedOut>> {
        let due = self.pacer.lock().unwrap().take_all()?;
        Some(self.hand_out(due))
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.ledger.forget_partitions(
            topic_partitions
                .iter()
                .map(|tp| (tp.topic.as_str(), tp.partition)),
        );
        self.pacer
            .lock()
            .unwrap()
            .forget_partitions(topic_partitions);
        for topic_partition in topic_partitions {
            publish(topic_partition, Held::default());
        }
    }
}

fn publish(topic_partition: &TopicPartition, uncommitted: Held) {
    let topic: Arc<str> = Arc::from(topic_partition.topic.as_str());
    let partition: Arc<str> = Arc::from(topic_partition.partition.to_string());
    gauge!(
        UNCOMMITTED_OFFSETS,
        "topic" => topic.clone(),
        "partition" => partition.clone()
    )
    .set(uncommitted.offsets as f64);
    gauge!(
        UNCOMMITTED_EVENTS,
        "topic" => topic.clone(),
        "partition" => partition.clone()
    )
    .set(uncommitted.charge.events as f64);
    gauge!(
        UNCOMMITTED_BYTES,
        "topic" => topic,
        "partition" => partition
    )
    .set(uncommitted.charge.bytes as f64);
}

#[cfg(test)]
mod tests {
    use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};

    use super::*;

    const EACH: Charge = Charge {
        events: 1,
        bytes: 100,
    };

    fn p0() -> TopicPartition {
        TopicPartition::new("events", 0)
    }

    fn held(offsets: usize) -> Held {
        Held {
            offsets,
            charge: Charge {
                events: offsets as u64,
                bytes: 100 * offsets as u64,
            },
        }
    }

    fn uncommitted() -> Uncommitted {
        Uncommitted::new(Arc::new(TopicOffsetLedger::new()), CommitPacer::immediate())
    }

    fn published(snapshotter: &Snapshotter, topic_partition: &TopicPartition) -> Held {
        let partition = topic_partition.partition.to_string();
        let mut published = Held::default();
        for (key, _, _, value) in snapshotter.snapshot().into_vec() {
            let DebugValue::Gauge(value) = value else {
                continue;
            };
            let labelled =
                key.key()
                    .labels()
                    .any(|label| label.key() == "partition" && label.value() == partition)
                    && key.key().labels().any(|label| {
                        label.key() == "topic" && label.value() == topic_partition.topic
                    });
            if !labelled {
                continue;
            }
            let value = value.into_inner();
            match key.key().name() {
                UNCOMMITTED_OFFSETS => published.offsets = value as usize,
                UNCOMMITTED_EVENTS => published.charge.events = value as u64,
                UNCOMMITTED_BYTES => published.charge.bytes = value as u64,
                _ => {}
            }
        }
        published
    }

    fn charge(uncommitted: &Uncommitted, generation: u64, offset: i64) -> Held {
        uncommitted
            .charge(&p0(), generation, &[(Offset(offset), EACH)])
            .expect("the ledger accepts the charge")
    }

    fn settled(uncommitted: &Uncommitted, offsets: &[i64]) {
        let frontier = uncommitted
            .settled(&p0(), 0, offsets.iter().map(|&o| Offset(o)))
            .expect("the ledger settles");
        assert!(frontier.is_some());
    }

    #[test]
    fn a_take_stays_uncommitted_until_the_pacer_hands_it_out() {
        let uncommitted = uncommitted();
        charge(&uncommitted, 0, 10);
        settled(&uncommitted, &[10]);

        assert_eq!(charge(&uncommitted, 0, 11), held(2));

        let handed_out = uncommitted.take_due(Instant::now()).expect("due");
        assert_eq!(
            handed_out,
            HashMap::from([(
                p0(),
                HandedOut {
                    offset: Offset(11),
                    remaining: held(1),
                }
            )])
        );
        assert_eq!(charge(&uncommitted, 0, 12), held(2));
    }

    #[test]
    fn takes_since_the_last_commit_add_up() {
        let uncommitted = uncommitted();
        charge(&uncommitted, 0, 10);
        charge(&uncommitted, 0, 11);
        settled(&uncommitted, &[10]);
        settled(&uncommitted, &[11]);

        assert_eq!(charge(&uncommitted, 0, 12), held(3));
    }

    #[test]
    fn a_take_moves_only_its_own_partitions_charge() {
        let uncommitted = uncommitted();
        let p1 = TopicPartition::new("events", 1);
        let charge_p1 = |offset: i64| {
            uncommitted
                .charge(&p1, 0, &[(Offset(offset), EACH)])
                .expect("the ledger accepts the charge")
        };
        charge(&uncommitted, 0, 10);
        charge_p1(20);
        settled(&uncommitted, &[10]);

        assert_eq!(charge_p1(21), held(2), "partition 0's take stays its own");

        uncommitted.take_due(Instant::now()).expect("due");
        assert_eq!(charge(&uncommitted, 0, 11), held(1));
        assert_eq!(charge_p1(22), held(3));
    }

    #[test]
    fn a_hand_out_carries_each_partitions_own_remaining_charge() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        let uncommitted = uncommitted();
        let p1 = TopicPartition::new("events", 1);
        charge(&uncommitted, 0, 10);
        charge(&uncommitted, 0, 11);
        for offset in [20, 21, 22] {
            uncommitted
                .charge(&p1, 0, &[(Offset(offset), EACH)])
                .expect("the ledger accepts the charge");
        }
        settled(&uncommitted, &[10]);
        uncommitted
            .settled(&p1, 0, [Offset(20)])
            .expect("the ledger settles");

        assert_eq!(
            uncommitted.take_due(Instant::now()).expect("due"),
            HashMap::from([
                (
                    p0(),
                    HandedOut {
                        offset: Offset(11),
                        remaining: held(1),
                    }
                ),
                (
                    p1.clone(),
                    HandedOut {
                        offset: Offset(21),
                        remaining: held(2),
                    }
                ),
            ])
        );
        assert_eq!(published(&snapshotter, &p0()), held(1));
        assert_eq!(published(&snapshotter, &p1), held(2));
    }

    #[test]
    fn a_forgotten_partition_drops_its_window_and_its_pending_take() {
        let uncommitted = uncommitted();
        charge(&uncommitted, 0, 10);
        charge(&uncommitted, 0, 11);
        settled(&uncommitted, &[10]);

        uncommitted.forget_partitions(&[p0()]);

        assert!(uncommitted.take_all().is_none());
        assert_eq!(charge(&uncommitted, 1, 10), held(1));
    }

    #[test]
    fn a_take_over_a_gap_moves_the_gap_offsets_to_the_pacer() {
        let uncommitted = uncommitted();
        charge(&uncommitted, 0, 10);
        let window = charge(&uncommitted, 0, 12);
        assert_eq!(
            window,
            Held {
                offsets: 3,
                charge: EACH + EACH
            }
        );

        settled(&uncommitted, &[10, 12]);

        assert_eq!(
            charge(&uncommitted, 0, 13),
            Held {
                offsets: 4,
                charge: EACH + EACH + EACH
            }
        );
    }

    #[test]
    fn the_gauges_follow_the_charge_until_the_frontier_is_handed_out() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
        let uncommitted = uncommitted();

        charge(&uncommitted, 0, 10);
        charge(&uncommitted, 0, 11);
        assert_eq!(published(&snapshotter, &p0()), held(2));

        settled(&uncommitted, &[10]);
        assert_eq!(
            published(&snapshotter, &p0()),
            held(2),
            "a take moves the charge"
        );

        uncommitted.take_due(Instant::now()).expect("due");
        assert_eq!(published(&snapshotter, &p0()), held(1));

        uncommitted.forget_partitions(&[p0()]);
        assert_eq!(published(&snapshotter, &p0()), Held::default());
    }
}
