use std::time::Duration;

use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka, KafkaContext, KafkaProduceError,
};
use rdkafka::error::KafkaError;
use rdkafka::producer::FutureProducer;
use thiserror::Error;
use tracing::warn;

use crate::types::{PropertyType, TupleKey};

#[derive(serde::Serialize)]
struct Outgoing<'a> {
    team_id: i64,
    property_type: PropertyType,
    property_key: &'a str,
    property_value: &'a str,
    property_count: u64,
}

#[derive(Debug, Error)]
pub enum ProduceError {
    #[error("kafka produce timed out after {0:?}")]
    Timeout(Duration),
    #[error("{failed}/{total} records failed delivery")]
    PartialFailure { failed: usize, total: usize },
}

/// Produce the aggregated tuples to the output topic. At-least-once: each
/// produce stands on its own and the caller stores the input consumer offsets
/// only after this returns Ok. On failure the caller does not advance the
/// stored offsets, so the next pod resumes from before these inputs and
/// re-produces them; duplicates are absorbed by the storage table's existing
/// aggregation semantics.
#[async_trait]
pub trait Producer: Send {
    async fn produce(&self, items: Vec<(TupleKey, u64)>) -> Result<(), ProduceError>;
}

pub struct AggregatedProducer {
    inner: FutureProducer<KafkaContext>,
    output_topic: String,
    produce_timeout: Duration,
}

impl AggregatedProducer {
    pub async fn new<L>(
        kafka_config: &KafkaConfig,
        liveness: L,
        output_topic: String,
        produce_timeout: Duration,
    ) -> Result<Self, KafkaError>
    where
        L: common_liveness::SyncLivenessReporter + Clone + 'static,
    {
        let inner = create_kafka_producer(kafka_config, liveness).await?;
        Ok(Self {
            inner,
            output_topic,
            produce_timeout,
        })
    }
}

#[async_trait]
impl Producer for AggregatedProducer {
    async fn produce(&self, items: Vec<(TupleKey, u64)>) -> Result<(), ProduceError> {
        if items.is_empty() {
            return Ok(());
        }
        let total = items.len();

        let messages: Vec<Outgoing> = items
            .iter()
            .map(|(tuple, count)| Outgoing {
                team_id: tuple.team_id,
                property_type: tuple.property_type,
                property_key: &tuple.property_key,
                property_value: &tuple.property_value,
                property_count: *count,
            })
            .collect();

        let send_fut = send_keyed_iter_to_kafka(
            &self.inner,
            &self.output_topic,
            |m| Some(format!("{}:{}", m.team_id, m.property_key)),
            messages,
        );

        let results = match tokio::time::timeout(self.produce_timeout, send_fut).await {
            Ok(r) => r,
            Err(_) => {
                warn!("kafka produce timed out after {:?}", self.produce_timeout);
                return Err(ProduceError::Timeout(self.produce_timeout));
            }
        };

        let failed = results
            .iter()
            .filter(|r| matches!(r, Err(KafkaProduceError::KafkaProduceError { .. })))
            .count();
        if failed > 0 {
            return Err(ProduceError::PartialFailure { failed, total });
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use proptest::prelude::*;

    /// Kafka's default partitioner (`murmur2_random_consistent`) is just
    /// `(murmur2(key) & 0x7fffffff) % num_partitions` when a key is provided.
    /// Reimplementing it here so the test exercises the same hash the
    /// producer will use in prod.
    fn murmur2(data: &[u8]) -> u32 {
        let seed = 0x9747b28c_u32;
        let m = 0x5bd1e995_u32;
        let r: u32 = 24;
        let length = data.len();

        let mut h = seed ^ (length as u32);
        let length4 = length / 4;

        for i in 0..length4 {
            let i4 = i * 4;
            let mut k = (data[i4] as u32)
                | ((data[i4 + 1] as u32) << 8)
                | ((data[i4 + 2] as u32) << 16)
                | ((data[i4 + 3] as u32) << 24);
            k = k.wrapping_mul(m);
            k ^= k >> r;
            k = k.wrapping_mul(m);
            h = h.wrapping_mul(m);
            h ^= k;
        }

        let tail = length & 3;
        let tail_start = length & !3;
        if tail >= 3 {
            h ^= (data[tail_start + 2] as u32) << 16;
        }
        if tail >= 2 {
            h ^= (data[tail_start + 1] as u32) << 8;
        }
        if tail >= 1 {
            h ^= data[tail_start] as u32;
            h = h.wrapping_mul(m);
        }

        h ^= h >> 13;
        h = h.wrapping_mul(m);
        h ^= h >> 15;
        h
    }

    fn partition_for(key: &str, num_partitions: usize) -> usize {
        let h = (murmur2(key.as_bytes()) & 0x7fffffff) as usize;
        h % num_partitions
    }

    const NUM_PARTITIONS: usize = 64;

    proptest! {
        /// Documents the bug we just fixed. The old key extractor —
        /// `|m| Some(m.team_id.to_string())` — produced the same Kafka key
        /// for every message from a given team, so all of that team's
        /// traffic landed on exactly one partition no matter how many
        /// distinct property keys it emitted.
        #[test]
        fn old_key_single_team_collapses_to_one_partition(
            team_id in i64::MIN..i64::MAX,
            property_keys in prop::collection::hash_set("[a-z_$][a-z0-9_$]{2,30}", 1..200),
        ) {
            let mut partitions = std::collections::HashSet::new();
            for _ in &property_keys {
                let old_kafka_key = team_id.to_string();
                partitions.insert(partition_for(&old_kafka_key, NUM_PARTITIONS));
            }
            prop_assert_eq!(partitions.len(), 1);
        }

        /// New key shape `team_id:property_key` spreads a single team's
        /// traffic across most of the topic's partitions, since a typical
        /// team emits hundreds of distinct property keys. Property: no
        /// single partition holds more than 20% of one team's messages
        /// when the team has at least 50 distinct property keys. Uniform
        /// expectation is ~1.5%; 20% is a wide margin to allow for the
        /// stochasticity of murmur2 on short, small-alphabet inputs.
        #[test]
        fn new_key_spreads_single_team_across_partitions(
            team_id in -1_000_000i64..1_000_000,
            property_keys in prop::collection::hash_set("[a-z_$][a-z0-9_$]{2,30}", 50..500),
        ) {
            let mut counts = [0usize; NUM_PARTITIONS];
            for key in &property_keys {
                let kafka_key = format!("{team_id}:{key}");
                counts[partition_for(&kafka_key, NUM_PARTITIONS)] += 1;
            }
            let total: usize = counts.iter().sum();
            let max = *counts.iter().max().unwrap();
            prop_assert!(
                max * 5 <= total,
                "hot partition: {max} of {total} ({}%) on a single partition for team {team_id}",
                (max * 100) / total
            );
        }

        /// Even when traffic is overwhelmingly skewed toward one team
        /// (mimicking team 2's outsized event volume), the new key spreads
        /// across many partitions because each team has many property
        /// keys. Property: the top partition holds < 25% of all traffic.
        #[test]
        fn new_key_handles_skewed_team_distribution(
            heavy_team in -1_000_000i64..1_000_000,
            heavy_keys in prop::collection::hash_set("[a-z_$][a-z0-9_$]{2,30}", 100..500),
            other_messages in prop::collection::vec(
                (-1_000_000i64..1_000_000, "[a-z_$][a-z0-9_$]{2,30}"),
                0..200,
            ),
        ) {
            let mut counts = [0usize; NUM_PARTITIONS];
            // Heavy team: each distinct property key is one entry. Partition
            // assignment depends only on key identity, not message count;
            // this models distinct tuples, not raw event volume.
            for key in &heavy_keys {
                let kafka_key = format!("{heavy_team}:{key}");
                counts[partition_for(&kafka_key, NUM_PARTITIONS)] += 1;
            }
            for (team_id, key) in &other_messages {
                let kafka_key = format!("{team_id}:{key}");
                counts[partition_for(&kafka_key, NUM_PARTITIONS)] += 1;
            }
            let total: usize = counts.iter().sum();
            let max = *counts.iter().max().unwrap();
            prop_assert!(
                max * 4 <= total,
                "skewed workload still hot-partitions: {max} of {total} ({}%) on one partition",
                (max * 100) / total
            );
        }
    }
}
