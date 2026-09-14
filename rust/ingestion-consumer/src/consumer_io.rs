//! External input and submission boundaries for the consumer runtime.

use std::time::Duration;

use futures::Stream;
use rdkafka::consumer::stream_consumer::MessageStream;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::{KafkaResult, RDKafkaErrorCode};
use rdkafka::message::{BorrowedMessage, Message};
use rdkafka::TopicPartitionList;

use crate::batcher::Batcher;
use crate::order_sentinel::SentinelContext;
use crate::scheduler::SchedulerKind;
use crate::types::Accumulator;

/// Kafka operations used by the runtime. Messages may borrow the client, so
/// production collection does not detach, copy, or box a message at this seam.
pub trait KafkaInput: Send + Sync + 'static {
    type Message<'a>: Message + Send
    where
        Self: 'a;

    type Stream<'a>: Stream<Item = KafkaResult<Self::Message<'a>>> + Send + Unpin
    where
        Self: 'a;

    /// Open one stream per collected batch. Polling it must be cancellation-safe.
    fn stream(&self) -> Self::Stream<'_>;

    fn context(&self) -> &SentinelContext;

    /// Enqueue an asynchronous offset commit.
    fn commit(&self, offsets: &TopicPartitionList) -> KafkaResult<()>;

    fn fatal_error(&self) -> Option<(RDKafkaErrorCode, String)>;

    /// Fetch broker-committed offsets for the current assignment. This may block
    /// and is called only from the commit monitor's blocking task. `None` means
    /// there is no assignment yet; partitions without stored offsets are omitted.
    fn fetch_committed_offsets(&self) -> KafkaResult<Option<Vec<(String, i32, i64)>>>;
}

impl KafkaInput for StreamConsumer<SentinelContext> {
    type Message<'a> = BorrowedMessage<'a>;

    type Stream<'a> = MessageStream<'a, SentinelContext>;

    fn stream(&self) -> Self::Stream<'_> {
        StreamConsumer::stream(self)
    }

    fn context(&self) -> &SentinelContext {
        Consumer::context(self)
    }

    fn commit(&self, offsets: &TopicPartitionList) -> KafkaResult<()> {
        Consumer::commit(self, offsets, CommitMode::Async)
    }

    fn fatal_error(&self) -> Option<(RDKafkaErrorCode, String)> {
        self.client().fatal_error()
    }

    fn fetch_committed_offsets(&self) -> KafkaResult<Option<Vec<(String, i32, i64)>>> {
        let assignment = self.assignment()?;
        if assignment.count() == 0 {
            return Ok(None);
        }
        let committed = self.committed_offsets(assignment, Duration::from_secs(5))?;
        Ok(Some(
            committed
                .elements()
                .iter()
                .filter_map(|element| match element.offset() {
                    rdkafka::Offset::Offset(offset) => {
                        Some((element.topic().to_string(), element.partition(), offset))
                    }
                    // Invalid = no offset stored for the partition yet.
                    _ => None,
                })
                .collect(),
        ))
    }
}

/// Submits polls in order and purges work lost during a rebalance. Completions
/// and fatal failures arrive separately through the batcher's output channels.
pub trait BatchSubmitter: Send + Sync + 'static {
    fn submit(&self, accumulator: Accumulator) -> u64;
    fn purge_revoked(&self, partitions: &[(String, i32)]);
    fn scheduler_kind(&self) -> SchedulerKind;
}

impl BatchSubmitter for Batcher {
    fn submit(&self, accumulator: Accumulator) -> u64 {
        Batcher::submit(self, accumulator)
    }

    fn purge_revoked(&self, partitions: &[(String, i32)]) {
        self.dispatcher().purge_revoked(partitions);
    }

    fn scheduler_kind(&self) -> SchedulerKind {
        self.dispatcher().scheduler_kind()
    }
}
