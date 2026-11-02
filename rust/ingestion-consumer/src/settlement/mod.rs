//! When accepted offsets reach the ledger and the commit pacer: per poll or per group.

mod budget;
#[cfg(test)]
mod fakes;
mod group;
mod poll;
mod uncommitted;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Charge, Held, Offset, Rejection, TopicOffsetLedger, TopicPartition};

use tracing::warn;

use crate::config::CompletionGranularity;
use crate::order_sentinel::OffsetSpan;
use crate::partition_budget::BudgetLimits;

use budget::PartitionBudget;
pub(crate) use group::GroupSettlement;
pub(crate) use poll::PollSettlement;
use uncommitted::Uncommitted;

pub(crate) struct ChargedSlice<'a> {
    pub(crate) topic_partition: &'a TopicPartition,
    pub(crate) generation: u64,
    pub(crate) span: OffsetSpan,
    pub(crate) charges: &'a [(Offset, Charge)],
}

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

    /// The oldest poll retired with every message accepted.
    fn settle_poll(&self, slices: &[ChargedSlice<'_>]) -> anyhow::Result<()>;

    fn take_due(&self, now: Instant) -> Option<Commit>;

    fn take_all(&self) -> Option<Commit>;

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);
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

pub(crate) fn for_granularity(
    granularity: CompletionGranularity,
    ledger: Arc<TopicOffsetLedger>,
    commit_interval: Duration,
    limits: BudgetLimits,
) -> Arc<dyn Settlement> {
    match granularity {
        CompletionGranularity::Poll => {
            if limits.is_set() {
                warn!(
                    "Ignoring the partition budget: it needs CONSUMER_COMPLETION_GRANULARITY=group"
                );
            }
            Arc::new(PollSettlement::new(ledger))
        }
        CompletionGranularity::Group => {
            Arc::new(GroupSettlement::new(ledger, commit_interval, limits))
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
