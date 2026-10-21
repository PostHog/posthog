use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::TopicOffsetLedger;
use futures::StreamExt;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::BorrowedMessage;
use tracing::warn;

use super::poll::{CollectedBatch, PollBuilder};
use crate::rebalance::RebalanceContext;

#[derive(Debug, Clone, Copy)]
pub(crate) struct PollLimits {
    pub(crate) batch_size: usize,
    /// Payload-byte bound; `0` disables it.
    pub(crate) batch_size_bytes: usize,
    pub(crate) batch_timeout: Duration,
}

pub(crate) struct Collector {
    consumer: Arc<StreamConsumer<RebalanceContext>>,
    ledger: Arc<TopicOffsetLedger>,
    limits: PollLimits,
    handle: Handle,
}

impl Collector {
    pub(crate) fn new(
        consumer: Arc<StreamConsumer<RebalanceContext>>,
        ledger: Arc<TopicOffsetLedger>,
        limits: PollLimits,
        handle: Handle,
    ) -> Self {
        Self {
            consumer,
            ledger,
            limits,
            handle,
        }
    }

    /// Collect messages from Kafka until the first of `batch_size` messages,
    /// `batch_size_bytes` of payload (when enabled), or `batch_timeout`.
    pub(crate) async fn collect_batch(&self) -> anyhow::Result<CollectedBatch> {
        let mut poll = PollBuilder::new();
        let deadline = Instant::now() + self.limits.batch_timeout;

        let mut stream = self.consumer.stream();

        loop {
            if self.is_full(&poll) {
                break;
            }

            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }

            let poll_wait = remaining.min(Duration::from_secs(10));
            match tokio::time::timeout(poll_wait, stream.next()).await {
                Ok(Some(Ok(borrowed_message))) => poll.add(&borrowed_message, &self.ledger),
                Ok(Some(Err(err))) => {
                    self.recv_failed(err)?;
                    break;
                }
                Ok(None) => break,
                Err(_) => {
                    self.handle.report_healthy();
                    if Instant::now() >= deadline {
                        break;
                    }
                }
            }
        }

        Ok(poll.finish())
    }

    /// One message from Kafka, or `None` after an error the client recovers
    /// from. Safe to cancel: a message is taken only when this returns.
    pub(crate) async fn receive(&self) -> anyhow::Result<Option<BorrowedMessage<'_>>> {
        match self.consumer.recv().await {
            Ok(message) => Ok(Some(message)),
            Err(err) => {
                self.recv_failed(err)?;
                Ok(None)
            }
        }
    }

    pub(crate) fn add(&self, poll: &mut PollBuilder, message: &BorrowedMessage<'_>) {
        poll.add(message, &self.ledger);
    }

    /// The byte bound counts only messages already added: a poll therefore
    /// always carries at least one message — a single payload larger than the
    /// whole bound still moves rather than wedging the partition — and
    /// overshoot is at most one message, itself bounded by
    /// `fetch.message.max.bytes`.
    pub(crate) fn is_full(&self, poll: &PollBuilder) -> bool {
        if poll.message_count() >= self.limits.batch_size {
            return true;
        }
        if self.limits.batch_size_bytes > 0 && poll.payload_bytes() >= self.limits.batch_size_bytes
        {
            counter!("ingestion_consumer_batches_byte_capped_total").increment(1);
            return true;
        }
        false
    }

    pub(crate) fn batch_timeout(&self) -> Duration {
        self.limits.batch_timeout
    }

    fn recv_failed(&self, err: KafkaError) -> anyhow::Result<()> {
        warn!(error = %err, "Kafka recv error");
        counter!("ingestion_consumer_kafka_errors_total").increment(1);
        // A fatal client error (such as UnreleasedInstanceId from a
        // static-membership collision) permanently disables the
        // consumer. Propagate it so the process exits and Kubernetes
        // restarts the pod, instead of re-polling a dead client forever
        // while still reporting healthy.
        if let Some((code, reason)) = self.consumer.client().fatal_error() {
            anyhow::bail!("fatal Kafka client error ({code:?}): {reason}");
        }
        Ok(())
    }
}
