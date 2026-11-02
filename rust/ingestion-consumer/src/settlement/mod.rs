//! When accepted offsets reach the ledger and the commit pacer: per group.

mod budget;
#[cfg(test)]
mod fakes;
mod group;
mod uncommitted;

use std::collections::HashMap;
use std::time::Instant;

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicPartition};

#[cfg(test)]
use common_kafka_consumer::TopicOffsetLedger;

use budget::PartitionBudget;
pub(crate) use group::GroupSettlement;
use uncommitted::Uncommitted;

pub(crate) trait Settlement: Send + Sync {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Charged, Rejection>;

    /// Accepted offsets from one poll's slice of a partition, charged under `generation`.
    fn settle_run(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: &[Offset],
    ) -> anyhow::Result<RunOutcome>;

    fn take_due(&self, now: Instant) -> Option<Commit>;

    fn take_all(&self) -> Option<Commit>;

    fn on_assigned(&self, assigned: &[TopicPartition]);

    fn on_revoked(&self, revoked: &[TopicPartition]);
}

pub(crate) trait Accounting: Send + Sync {
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Held, Rejection>;
    fn settled(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<Option<Offset>, Rejection>;
    fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, HandedOut>>;
    fn take_all(&self) -> Option<HashMap<TopicPartition, HandedOut>>;
    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct HandedOut {
    pub(crate) offset: Offset,
    pub(crate) remaining: Held,
}

pub(crate) trait Admission: Send + Sync {
    fn charged(&self, topic_partition: &TopicPartition, uncommitted: Charge) -> Option<Pause>;
    fn handed_out(&self, handed_out: &HashMap<TopicPartition, HandedOut>) -> Vec<TopicPartition>;

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RunOutcome {
    Settled,
    /// Charged under a generation that a rebalance has since replaced.
    Stale,
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Pause;

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Charged {
    pub(crate) uncommitted: Charge,
    pub(crate) pause: Option<Pause>,
}

pub(crate) struct Commit {
    pub(crate) offsets: HashMap<TopicPartition, Offset>,
    pub(crate) uncommitted: HashMap<TopicPartition, Charge>,
    pub(crate) resume: Vec<TopicPartition>,
}

impl Commit {
    fn new(handed_out: HashMap<TopicPartition, HandedOut>, resume: Vec<TopicPartition>) -> Self {
        let mut offsets = HashMap::with_capacity(handed_out.len());
        let mut uncommitted = HashMap::with_capacity(handed_out.len());
        for (topic_partition, handed_out) in handed_out {
            uncommitted.insert(topic_partition.clone(), handed_out.remaining.charge);
            offsets.insert(topic_partition, handed_out.offset);
        }
        Self {
            offsets,
            uncommitted,
            resume,
        }
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
