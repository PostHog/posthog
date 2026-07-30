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

    /// Verify the seed topic's broker partition count equals the consumer's partitioner modulus.
    /// The producer routes with `murmur2_random` — `murmur2(key) % <broker partition count>` —
    /// while the consumer owns a person by `partition_for(key, COHORT_PARTITION_COUNT)`. The two
    /// agree only when the topic has exactly that many partitions; on any other count a person's
    /// seed tiles land on a worker that does not own their live-stream state, so startup must
    /// refuse to run. Blocking — call via `spawn_blocking` from async contexts.
    pub fn verify_partition_count(
        &self,
        expected: u32,
        timeout: Duration,
    ) -> Result<(), PartitionCountError> {
        let metadata = self
            .producer
            .client()
            .fetch_metadata(Some(&self.topic), timeout)
            .map_err(PartitionCountError::Metadata)?;
        let topic = metadata
            .topics()
            .iter()
            .find(|topic| topic.name() == self.topic)
            .ok_or_else(|| PartitionCountError::Missing {
                topic: self.topic.clone(),
            })?;
        if let Some(error) = topic.error() {
            return Err(PartitionCountError::Topic {
                topic: self.topic.clone(),
                code: error.into(),
            });
        }
        let actual = topic.partitions().len();
        if u64::try_from(actual) != Ok(u64::from(expected)) {
            return Err(PartitionCountError::Mismatch {
                topic: self.topic.clone(),
                actual,
                expected,
            });
        }
        Ok(())
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

/// Why the seed topic failed its startup partition-count verification. Every variant is fatal:
/// producing to a mis-provisioned topic splits seeded membership from live state silently.
#[derive(Debug, thiserror::Error)]
pub enum PartitionCountError {
    #[error("fetching seed topic metadata")]
    Metadata(#[source] KafkaError),
    #[error("seed topic {topic:?} is not present in broker metadata")]
    Missing { topic: String },
    #[error("seed topic {topic:?} metadata reports {code}")]
    Topic {
        topic: String,
        code: RDKafkaErrorCode,
    },
    #[error(
        "seed topic {topic:?} has {actual} partitions, expected {expected}: seed tiles would land \
         on workers that do not own their person"
    )]
    Mismatch {
        topic: String,
        actual: usize,
        expected: u32,
    },
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
