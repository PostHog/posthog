//! How the consumer loop turns what it receives into what it does next. The
//! consumer owns the Kafka client and the batcher outputs, hands each event to
//! the polling strategy, and carries out the [`Step`]s the strategy returns.

mod capped;
mod collector;
mod continuous;
#[cfg(test)]
mod harness;
mod poll;
mod select;

use std::sync::Arc;

use common_kafka_consumer::{GroupCompletion, TopicPartition};
use metrics::counter;
use rdkafka::message::Message;
use tokio::time::Instant;
use tracing::info;

use crate::debug_recorder::DebugRecorder;
use crate::settlement::{Commit, Settlement};

pub(crate) use capped::CappedPolling;
use collector::Collector;
pub(crate) use collector::PollLimits;
pub(crate) use continuous::ContinuousPolling;
pub(crate) use poll::{
    debug_partition_offsets, debug_partition_spans, BatchStats, CollectedBatch, InFlightPoll,
    PartitionDeliveries,
};
pub(crate) use select::{select, Selected};

pub(crate) enum Step {
    /// Charge the poll, submit it to the batcher, and hand it back through
    /// [`PollingStrategy::submitted`].
    Submit(CollectedBatch),
    /// Submit the offsets and resume the partitions.
    Commit(Commit),
    /// Shutdown drained the in-flight work.
    Stop,
    Fail(anyhow::Error),
}

pub(crate) struct Parts {
    pub(crate) limits: PollLimits,
    pub(crate) settlement: Arc<dyn Settlement>,
    pub(crate) group_id: String,
    pub(crate) debug_recorder: Option<Arc<DebugRecorder>>,
}

/// What the consumer loop asks of a polling strategy. The loop hands it each
/// event and carries out the steps it returns.
pub(crate) trait PollingStrategy {
    fn reading(&mut self) -> bool;

    fn deadline(&self) -> Option<Instant>;

    fn received<M: Message>(&mut self, message: &M, now: Instant);

    fn completed(&mut self, completion: &GroupCompletion) -> anyhow::Result<()>;

    fn ticked(&mut self);

    /// Every message received before the revoke belongs to the old
    /// assignment: the batcher purges it, or Kafka delivers it again from the
    /// last commit.
    fn revoked(&mut self, topic_partitions: &[TopicPartition]);

    /// The poll in progress is not charged yet, so it is dropped and replays
    /// from the last commit.
    fn shutdown(&mut self);

    fn submitted(&mut self, poll: InFlightPoll);

    fn next_step(&mut self, now: Instant) -> Option<Step>;
}

fn report_revoked(stripped: u64) {
    if stripped > 0 {
        counter!("ingestion_consumer_polls_dropped_on_revoke_total").increment(stripped);
        info!(stripped, "Removed revoked partitions' messages");
    }
}
