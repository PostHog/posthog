//! When accepted offsets reach the ledger and the commit pacer: per poll or per group.

mod group;
mod poll;

use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::{Charge, Offset, TopicOffsetLedger, TopicPartition};

use crate::commit_pacer::CommitPacer;
use crate::config::CompletionGranularity;
use crate::order_sentinel::OffsetSpan;

pub(crate) use group::GroupSettlement;
pub(crate) use poll::PollSettlement;

pub(crate) struct ChargedSlice<'a> {
    pub(crate) topic_partition: &'a TopicPartition,
    pub(crate) generation: u64,
    pub(crate) span: OffsetSpan,
    pub(crate) charges: &'a [(Offset, Charge)],
}

pub(crate) trait Settlement: Send + Sync {
    /// Accepted offsets from one poll's slice of a partition, charged under `generation`.
    fn settle_run(&self, topic_partition: &TopicPartition, generation: u64, offsets: &[Offset]);

    /// The oldest poll retired with every message accepted.
    fn settle_poll(&self, slices: &[ChargedSlice<'_>]);

    fn pacer(&self) -> &Arc<CommitPacer>;

    fn forget_partitions(&self, topic_partitions: &[TopicPartition]) {
        self.pacer().forget_partitions(topic_partitions);
    }
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
