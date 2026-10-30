//! How the consumer loop turns what it receives into what it does next. The
//! consumer owns the Kafka client and the batcher outputs, hands each event to
//! the polling strategy, and carries out the [`Step`]s the strategy returns.

mod collector;
mod continuous;
#[cfg(test)]
mod harness;
mod poll;

use std::sync::Arc;

use common_kafka_consumer::{GroupCompletion, TopicPartition};
use metrics::counter;
use rdkafka::message::Message;
use tokio::time::Instant;
use tracing::info;

use crate::settlement::{Commit, GroupSettlement};

use collector::Collector;
pub(crate) use collector::PollLimits;
pub(crate) use continuous::ContinuousPolling;
pub(crate) use poll::{
    debug_partition_offsets, debug_partition_spans, BatchStats, CollectedBatch, InFlightPoll,
    PartitionDeliveries,
};

pub(crate) enum Step {
    /// Charge the poll, submit it to the batcher, and hand it back through
    /// [`PollingStrategy::submitted`].
    Submit(CollectedBatch),
    /// Submit the offsets and resume the partitions.
    Commit(Commit),
    /// Shutdown drained the in-flight work.
    Stop,
}

pub(crate) struct Parts {
    pub(crate) limits: PollLimits,
    pub(crate) settlement: Arc<GroupSettlement>,
    pub(crate) group_id: String,
}

pub(crate) trait PollingStrategy {
    fn reading(&mut self) -> bool;

    fn deadline(&self) -> Option<Instant>;

    fn on_received<M: Message>(&mut self, message: &M, now: Instant);

    fn on_completed(&mut self, completion: &GroupCompletion) -> anyhow::Result<()>;

    fn on_ticked(&mut self);

    /// Submitted messages keep settling until [`Self::on_drain_finished`].
    fn on_drain_started(&mut self, topic_partitions: &[TopicPartition]);

    /// Takes every frontier, for the commit before the unassign, then drops
    /// the partitions as [`Self::on_revoked`] does, also on an error.
    fn on_drain_finished(
        &mut self,
        topic_partitions: &[TopicPartition],
    ) -> anyhow::Result<Option<Commit>>;

    /// Every message received before the revoke belongs to the old
    /// assignment: the batcher purges it, or Kafka delivers it again from the
    /// last commit.
    fn on_revoked(&mut self, topic_partitions: &[TopicPartition]);

    /// The poll in progress is not charged yet, so it is dropped and replays
    /// from the last commit.
    fn on_shutdown(&mut self);

    fn on_submitted(&mut self, poll: InFlightPoll);

    fn next_step(&mut self, now: Instant) -> Option<Step>;
}

fn report_revoked(stripped: u64) {
    if stripped > 0 {
        counter!("ingestion_consumer_polls_dropped_on_revoke_total").increment(stripped);
        info!(stripped, "Removed revoked partitions' messages");
    }
}
