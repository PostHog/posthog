//! When accepted offsets reach the ledger and the commit pacer: per poll or per group.

mod group;
mod poll;

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicOffsetLedger, TopicPartition};
use metrics::gauge;

use crate::commit_pacer::CommitPacer;
use crate::config::CompletionGranularity;
use crate::order_sentinel::OffsetSpan;

const UNCOMMITTED_OFFSETS: &str = "kafka_consumer_ledger_uncommitted_offsets";
const UNCOMMITTED_EVENTS: &str = "kafka_consumer_ledger_uncommitted_events";
const UNCOMMITTED_BYTES: &str = "kafka_consumer_ledger_uncommitted_bytes";

pub(crate) use group::GroupSettlement;
pub(crate) use poll::PollSettlement;

pub(crate) struct ChargedSlice<'a> {
    pub(crate) topic_partition: &'a TopicPartition,
    pub(crate) generation: u64,
    pub(crate) span: OffsetSpan,
    pub(crate) charges: &'a [(Offset, Charge)],
}

pub(crate) trait Settlement: Send + Sync {
    /// One poll's delivered offsets on a partition. Returns what the partition
    /// holds uncommitted after the charge.
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Held, Rejection>;

    /// Accepted offsets from one poll's slice of a partition, charged under `generation`.
    fn settle_run(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: &[Offset],
    ) -> anyhow::Result<()>;

    /// The oldest poll retired with every message accepted.
    fn settle_poll(&self, slices: &[ChargedSlice<'_>]) -> anyhow::Result<()>;

    fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>>;

    fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>>;

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);
}

/// A partition's uncommitted charge is in exactly one of two places: the
/// ledger's window until a take, then the pacer until the commit goes out.
/// Every move between them and every read of both hold the pacer's lock, so
/// no read counts a take twice or misses it.
struct Uncommitted {
    ledger: Arc<TopicOffsetLedger>,
    pacer: Mutex<CommitPacer>,
}

impl Uncommitted {
    fn new(ledger: Arc<TopicOffsetLedger>, pacer: CommitPacer) -> Self {
        Self {
            ledger,
            pacer: Mutex::new(pacer),
        }
    }

    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Held, Rejection> {
        let uncommitted = {
            let pacer = self.pacer.lock().unwrap();
            let held = self
                .ledger
                .charge(topic_partition, generation, charges.iter().copied())?;
            held + pacer.pending(topic_partition)
        };
        publish(topic_partition, uncommitted);
        Ok(uncommitted)
    }

    /// Move the partition's completed prefix from the ledger to the pacer.
    /// `false` when nothing has completed at the front of its window.
    fn take_frontier(&self, topic_partition: &TopicPartition) -> bool {
        let mut pacer = self.pacer.lock().unwrap();
        match self.ledger.take_frontier(topic_partition) {
            Some(taken) => {
                pacer.advance_frontier(topic_partition, taken);
                true
            }
            None => false,
        }
    }

    fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>> {
        self.take(|pacer| pacer.take_due(now))
    }

    fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>> {
        self.take(CommitPacer::take_all)
    }

    /// The pacer's charge for what it hands out ends here: the consumer
    /// submits the commit next.
    fn take(
        &self,
        take: impl FnOnce(&mut CommitPacer) -> Option<HashMap<TopicPartition, Offset>>,
    ) -> Option<HashMap<TopicPartition, Offset>> {
        let (due, remaining) = {
            let mut pacer = self.pacer.lock().unwrap();
            let due = take(&mut pacer)?;
            let remaining: Vec<(TopicPartition, Held)> = due
                .keys()
                .map(|topic_partition| (topic_partition.clone(), self.ledger.held(topic_partition)))
                .collect();
            (due, remaining)
        };
        for (topic_partition, held) in &remaining {
            publish(topic_partition, *held);
        }
        Some(due)
    }

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        {
            let mut pacer = self.pacer.lock().unwrap();
            self.ledger.forget_partitions(
                topic_partitions
                    .iter()
                    .map(|tp| (tp.topic.as_str(), tp.partition)),
            );
            pacer.forget_partitions(topic_partitions);
        }
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

pub(crate) fn for_granularity(
    granularity: CompletionGranularity,
    ledger: Arc<TopicOffsetLedger>,
    commit_interval: Duration,
) -> Arc<dyn Settlement> {
    match granularity {
        CompletionGranularity::Poll => Arc::new(PollSettlement::new(ledger)),
        CompletionGranularity::Group => Arc::new(GroupSettlement::new(ledger, commit_interval)),
    }
}

#[cfg(test)]
pub(crate) fn charge_offsets(
    ledger: &TopicOffsetLedger,
    topic_partition: &TopicPartition,
    generation: u64,
    offsets: &[i64],
) {
    ledger
        .charge(
            topic_partition,
            generation,
            offsets.iter().map(|&o| (Offset(o), Charge::ZERO)),
        )
        .expect("the test ledger accepts the charge");
}
