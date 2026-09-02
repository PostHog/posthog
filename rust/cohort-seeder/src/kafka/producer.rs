//! Kafka layer: the seed-tile producer client. Depends only on `domain`; never on `store`.
//!
//! This is a thin client — `new`/`enqueue`/`flush` and the health reporter. The produce sequencing
//! (pacing, in-flight bound, mark-produced, delivery acks) lives above, in the orchestrator, so this
//! module carries no PostgreSQL dependency.

use std::time::{Duration, Instant};

use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_liveness::SyncLivenessReporter;
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};

use crate::domain::{
    NextOffset, PersonSeed, ReconcileTile, SeedTile, WatchPartition, WatchPositions,
};

pub use crate::domain::partition::{SeedPartition, SeedPartitionCountError, SeedPartitions};

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

    pub fn enqueue_person(&self, seed: &PersonSeed) -> Result<DeliveryFuture, EnqueueError> {
        let payload = serde_json::to_vec(seed).expect("PersonSeed serialization cannot fail");
        let key = seed.partition_key();
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

    /// Capture the marker topic's per-partition high watermarks as the marker watcher's start
    /// positions. The high watermark is the offset the next record *will* receive, so it is exactly
    /// the first offset the watcher must read — no clock or "latest committed" assumption. Callers
    /// capture these BEFORE producing reconcile tiles: markers acked after this point sit at or above
    /// these positions, so the watcher started here cannot miss a marker of this dispatch. A manual
    /// disaster-recovery fallback could instead resolve positions via `offsets_for_times`; that is
    /// intentionally not implemented here. Blocking — call via `spawn_blocking` from async contexts.
    ///
    /// `budget` bounds the whole capture, not each call: watermarks come one partition at a time, so
    /// a per-call timeout would let a degraded broker hold the thread for `partitions × timeout`.
    pub fn capture_topic_offsets(
        &self,
        topic: &str,
        budget: Duration,
    ) -> Result<WatchPositions, CaptureOffsetsError> {
        let deadline = Instant::now() + budget;
        let remaining = |deadline: Instant| {
            deadline
                .checked_duration_since(Instant::now())
                .filter(|left| !left.is_zero())
                .ok_or_else(|| CaptureOffsetsError::BudgetExhausted {
                    topic: topic.to_string(),
                    budget,
                })
        };
        let partitions = self.topic_partition_ids(topic, remaining(deadline)?)?;
        let client = self.producer.client();
        let mut positions = WatchPositions::new();
        for partition in partitions {
            let (_low, high) = client
                .fetch_watermarks(topic, partition, remaining(deadline)?)
                .map_err(|source| CaptureOffsetsError::Watermarks {
                    topic: topic.to_string(),
                    partition,
                    source,
                })?;
            positions.insert(
                WatchPartition::new(partition),
                NextOffset::from_high_watermark(high),
            );
        }
        Ok(positions)
    }

    /// Prove `topic` exists and reports partitions. Metadata-only, so it costs one round trip where
    /// [`Self::capture_topic_offsets`] costs another per partition: a preflight needs existence, and
    /// the offsets it would collect are stale the moment it returns. Blocking — call via
    /// `spawn_blocking` from async contexts.
    pub fn verify_topic_reachable(
        &self,
        topic: &str,
        timeout: Duration,
    ) -> Result<(), CaptureOffsetsError> {
        self.topic_partition_ids(topic, timeout).map(|_| ())
    }

    /// The topic's partition ids, with the "is this topic actually there" checks the offset capture
    /// and the reachability probe share. A topic reporting no partitions is refused here: an empty
    /// position set would be vacuously "caught up", minting a settlement proof over nothing.
    fn topic_partition_ids(
        &self,
        topic: &str,
        timeout: Duration,
    ) -> Result<Vec<i32>, CaptureOffsetsError> {
        let metadata = self
            .producer
            .client()
            .fetch_metadata(Some(topic), timeout)
            .map_err(CaptureOffsetsError::Metadata)?;
        let topic_metadata = metadata
            .topics()
            .iter()
            .find(|entry| entry.name() == topic)
            .ok_or_else(|| CaptureOffsetsError::Missing {
                topic: topic.to_string(),
            })?;
        if let Some(error) = topic_metadata.error() {
            return Err(CaptureOffsetsError::Topic {
                topic: topic.to_string(),
                code: error.into(),
            });
        }
        if topic_metadata.partitions().is_empty() {
            return Err(CaptureOffsetsError::NoPartitions {
                topic: topic.to_string(),
            });
        }
        Ok(topic_metadata
            .partitions()
            .iter()
            .map(|partition| partition.id())
            .collect())
    }
}

/// Why a marker-topic metadata read failed — capturing the watch start positions, or the startup
/// probe that only proves the topic is there. The dispatch cannot record a resumable watch state
/// without those positions, so every variant aborts the dispatch (it re-converges on the next tick).
#[derive(Debug, thiserror::Error)]
pub enum CaptureOffsetsError {
    #[error("fetching marker topic metadata")]
    Metadata(#[source] KafkaError),
    #[error("marker topic {topic:?} is not present in broker metadata")]
    Missing { topic: String },
    #[error("marker topic {topic:?} metadata reports {code}")]
    Topic {
        topic: String,
        code: RDKafkaErrorCode,
    },
    #[error("marker topic {topic:?} reports no partitions")]
    NoPartitions { topic: String },
    #[error("capturing marker topic {topic:?} offsets exceeded its {budget:?} budget")]
    BudgetExhausted { topic: String, budget: Duration },
    #[error("fetching watermarks for marker topic {topic:?} partition {partition}")]
    Watermarks {
        topic: String,
        partition: i32,
        #[source]
        source: KafkaError,
    },
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
    fn reconcile_key_identifies_the_run_and_cohort() {
        let tile = ReconcileTile::new(
            TeamId(2),
            CohortId(42),
            crate::domain::ReconcileScope::Behavioral(
                crate::domain::BehavioralShapeHash::parse("shape").unwrap(),
            ),
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
