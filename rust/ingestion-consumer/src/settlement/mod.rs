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
    ) -> Result<Option<Pause>, Rejection>;

    /// Accepted offsets from one poll's slice of a partition, charged under `generation`.
    fn settle_run(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: &[Offset],
    ) -> anyhow::Result<()>;

    /// The oldest poll retired with every message accepted.
    fn settle_poll(&self, slices: &[ChargedSlice<'_>]) -> anyhow::Result<()>;

    fn take_due(&self, now: Instant) -> Option<Commit>;

    fn take_all(&self) -> Option<Commit>;

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);

    fn paused(&self) -> Vec<TopicPartition>;
}

/// A partition's uncommitted charge: what it has charged and no handed-out
/// frontier covers yet.
pub(crate) trait Accounting: Send + Sync {
    /// Returns the partition's uncommitted charge after this one.
    fn charge(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        charges: &[(Offset, Charge)],
    ) -> Result<Held, Rejection>;

    /// Called after a group run or a poll settles: marks offsets complete.
    /// Returns the frontier that results, `None` while the front of the
    /// partition's window is still incomplete. Leaves the uncommitted charge
    /// unchanged.
    fn settled(
        &self,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: impl IntoIterator<Item = Offset>,
    ) -> Result<Option<Offset>, Rejection>;

    /// Hands out the frontiers due for commit, and their charge stops
    /// counting: the consumer submits their commit right after.
    fn take_due(&self, now: Instant) -> Option<HashMap<TopicPartition, Offset>>;

    /// Like `take_due`, without waiting for the interval.
    fn take_all(&self) -> Option<HashMap<TopicPartition, Offset>>;

    /// Drops everything the partitions hold.
    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);

    fn held(&self, topic_partition: &TopicPartition) -> Held;
}

/// Pause and resume decisions from a partition's uncommitted charge.
pub(crate) trait Admission: Send + Sync {
    /// After a charge that left the partition at `uncommitted`.
    fn charged(&self, topic_partition: &TopicPartition, uncommitted: Charge) -> Option<Pause>;

    /// After a hand-out that left the partition at `uncommitted`.
    fn handed_out(&self, topic_partition: &TopicPartition, uncommitted: Charge) -> Option<Resume>;

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]);

    fn paused(&self) -> Vec<TopicPartition>;
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Pause;

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Resume;

pub(crate) struct Commit {
    pub(crate) offsets: HashMap<TopicPartition, Offset>,
    pub(crate) resume: Vec<TopicPartition>,
}

impl Commit {
    fn without_resumes(offsets: HashMap<TopicPartition, Offset>) -> Self {
        Self {
            offsets,
            resume: Vec::new(),
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
