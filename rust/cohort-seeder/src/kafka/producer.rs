//! Kafka layer: the seed-tile producer client. Depends only on `domain`; never on `store`.
//!
//! This is a thin client — `new`/`enqueue`/`flush` and the health reporter. The produce sequencing
//! (pacing, in-flight bound, mark-produced, delivery acks) lives above, in the orchestrator, so this
//! module carries no PostgreSQL dependency.

use std::time::Duration;

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_liveness::SyncLivenessReporter;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};

use crate::domain::SeedTile;

#[derive(Debug, thiserror::Error)]
pub enum EnqueueError {
    #[error("producer queue full")]
    QueueFull,
    #[error("fatal enqueue error: {0}")]
    Fatal(KafkaError),
}

impl From<KafkaError> for EnqueueError {
    fn from(error: KafkaError) -> Self {
        match error {
            KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull) => Self::QueueFull,
            other => Self::Fatal(other),
        }
    }
}

#[derive(Clone)]
pub struct SeedTileProducer {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl SeedTileProducer {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self, KafkaError> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy).await?;
        Ok(Self { producer, topic })
    }

    pub fn enqueue(&self, tile: &SeedTile) -> Result<DeliveryFuture, EnqueueError> {
        let payload = serde_json::to_vec(tile).expect("SeedTile serialization cannot fail");
        let key = tile.partition_key();
        let record = FutureRecord::to(&self.topic).key(&key).payload(&payload);
        self.producer
            .send_result(record)
            .map_err(|(error, _)| error.into())
    }

    pub fn flush(&self, timeout: Duration) -> Result<(), KafkaError> {
        self.producer.flush(timeout)
    }
}

#[derive(Clone, Copy)]
struct AlwaysHealthy;

impl SyncLivenessReporter for AlwaysHealthy {
    fn report_healthy(&self) {}

    fn report_unhealthy(&self) {}
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
