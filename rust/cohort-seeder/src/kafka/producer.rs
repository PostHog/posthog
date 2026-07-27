//! Kafka layer: the seed-tile producer client. Depends only on `domain`; never on `store`.
//!
//! This is a thin client — `new`/`enqueue`/`flush` and the health reporter. The produce sequencing
//! (pacing, in-flight bound, mark-produced, delivery acks) lives above, in the orchestrator, so this
//! module carries no PostgreSQL dependency.

use std::fmt;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_liveness::SyncLivenessReporter;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};

use crate::domain::{ReconcileTile, SeedTile};

const MAX_SEED_PARTITION_COUNT: u32 = 65_536;

/// A seed-topic partition proven to fit both Kafka's signed partition field and this service's
/// compact partition representation. Values can only be minted by [`SeedPartition::all`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SeedPartition(u16);

impl SeedPartition {
    pub fn all(count: u32) -> Result<SeedPartitions, SeedPartitionCountError> {
        if count == 0 {
            return Err(SeedPartitionCountError::Zero);
        }
        if count > MAX_SEED_PARTITION_COUNT {
            return Err(SeedPartitionCountError::TooLarge(count));
        }
        Ok(SeedPartitions { next: 0, count })
    }

    pub const fn as_u16(self) -> u16 {
        self.0
    }

    const fn as_i32(self) -> i32 {
        self.0 as i32
    }
}

impl fmt::Display for SeedPartition {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// The exact sequence `0..count` returned after [`SeedPartition::all`] proves every index fits.
#[derive(Debug, Clone)]
pub struct SeedPartitions {
    next: u32,
    count: u32,
}

impl Iterator for SeedPartitions {
    type Item = SeedPartition;

    fn next(&mut self) -> Option<Self::Item> {
        if self.next == self.count {
            return None;
        }
        let partition = u16::try_from(self.next)
            .expect("partition count validation proves every partition index fits u16");
        self.next += 1;
        Some(SeedPartition(partition))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let remaining = usize::try_from(self.count - self.next)
            .expect("a u32 partition count fits usize on supported targets");
        (remaining, Some(remaining))
    }
}

impl ExactSizeIterator for SeedPartitions {}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum SeedPartitionCountError {
    #[error("seed partition count must be greater than zero")]
    Zero,
    #[error(
        "seed partition count {0} exceeds the largest u16-indexed partition set ({MAX_SEED_PARTITION_COUNT})"
    )]
    TooLarge(u32),
}

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

    pub fn enqueue_reconcile(
        &self,
        tile: &ReconcileTile,
        partition: SeedPartition,
    ) -> Result<DeliveryFuture, EnqueueError> {
        let payload = serde_json::to_vec(tile).expect("ReconcileTile serialization cannot fail");
        let key = reconcile_partition_key(tile);
        let record = FutureRecord::to(&self.topic)
            .partition(partition.as_i32())
            .key(&key)
            .payload(&payload);
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

fn reconcile_partition_key(tile: &ReconcileTile) -> String {
    format!(
        "{}:{}:{}",
        tile.team_id().0,
        tile.cohort_id().0,
        tile.run_id().0
    )
}

#[cfg(test)]
mod tests {
    use cohort_core::filters::{CohortId, TeamId};
    use uuid::Uuid;

    use super::*;

    #[test]
    fn seed_partitions_cover_exactly_the_valid_partition_domain() {
        let partitions = SeedPartition::all(64).unwrap().collect::<Vec<_>>();
        assert_eq!(partitions.len(), 64);
        assert_eq!(partitions.first().unwrap().as_u16(), 0);
        assert_eq!(partitions.last().unwrap().as_u16(), 63);

        assert_eq!(
            SeedPartition::all(MAX_SEED_PARTITION_COUNT)
                .unwrap()
                .last()
                .unwrap()
                .as_u16(),
            u16::MAX,
        );
        assert!(matches!(
            SeedPartition::all(0),
            Err(SeedPartitionCountError::Zero)
        ));
        assert!(matches!(
            SeedPartition::all(MAX_SEED_PARTITION_COUNT + 1),
            Err(SeedPartitionCountError::TooLarge(count))
                if count == MAX_SEED_PARTITION_COUNT + 1
        ));
    }

    #[test]
    fn reconcile_key_identifies_the_run_and_cohort() {
        let tile = ReconcileTile::new(
            TeamId(2),
            CohortId(42),
            crate::domain::BehavioralShapeHash::parse("shape").unwrap(),
            crate::domain::RunId(Uuid::nil()),
        );

        assert_eq!(
            reconcile_partition_key(&tile),
            "2:42:00000000-0000-0000-0000-000000000000"
        );
    }

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
