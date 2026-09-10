//! Kafka producer for `cohort_stream_events`. The `murmur2_random` partitioner is pinned in
//! [`crate::config`]; this module only supplies the key via [`CohortStreamEvent::partition_key`].

use std::time::Duration;

use anyhow::{Context, Result};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_liveness::SyncLivenessReporter;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};

use crate::event::CohortStreamEvent;

/// Liveness is owned by the pipeline loop's commit-freshness gate: a wedged producer stops
/// acks, which stops commits, which withholds the consumer heartbeat. The stats callback
/// therefore reports nothing rather than double-owning the signal.
#[derive(Clone, Copy)]
struct AlwaysHealthy;

impl SyncLivenessReporter for AlwaysHealthy {
    fn report_healthy(&self) {}
    fn report_unhealthy(&self) {}
}

/// Enqueue failure, split by retriability: `QueueFull` means librdkafka's local buffer is at
/// capacity and the same event can be retried after a backoff; anything else is fatal for this
/// event (abandon and move on).
#[derive(Debug, thiserror::Error)]
pub enum EnqueueError {
    #[error("producer queue full")]
    QueueFull,
    #[error("fatal enqueue error: {0}")]
    Fatal(KafkaError),
}

impl From<KafkaError> for EnqueueError {
    fn from(err: KafkaError) -> Self {
        match err {
            KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull) => Self::QueueFull,
            other => Self::Fatal(other),
        }
    }
}

#[derive(Clone)]
pub struct CohortStreamProducer {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl CohortStreamProducer {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_stream_events producer")?;
        Ok(Self { producer, topic })
    }

    /// Hands the event to librdkafka without awaiting delivery; the returned future resolves on
    /// broker ack. rdkafka copies the payload, so nothing is borrowed after this returns.
    pub fn enqueue(&self, event: &CohortStreamEvent) -> Result<DeliveryFuture, EnqueueError> {
        let payload =
            serde_json::to_vec(event).expect("CohortStreamEvent serialization cannot fail");
        let key = event.partition_key();
        let record = FutureRecord::to(&self.topic).key(&key).payload(&payload);
        self.producer
            .send_result(record)
            .map_err(|(err, _)| err.into())
    }

    /// Blocking: waits for outstanding deliveries; call from `spawn_blocking`.
    pub fn flush(&self, timeout: Duration) -> Result<(), KafkaError> {
        self.producer.flush(timeout)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn enqueue_error_splits_queue_full_from_fatal() {
        assert!(matches!(
            EnqueueError::from(KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull)),
            EnqueueError::QueueFull
        ));
        assert!(matches!(
            EnqueueError::from(KafkaError::MessageProduction(
                RDKafkaErrorCode::MessageSizeTooLarge
            )),
            EnqueueError::Fatal(_)
        ));
        assert!(matches!(
            EnqueueError::from(KafkaError::Canceled),
            EnqueueError::Fatal(_)
        ));
    }
}
