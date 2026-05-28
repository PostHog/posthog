//! Kafka producer for `cohort_stream_events` (TDD §2.2, §4.3).
//!
//! Re-publishes each forwarded [`CohortStreamEvent`] keyed by [`partition_key`] so
//! `cohort-stream-processor`'s Stage 1 consumes it with per-`(team_id, person_id)` partition
//! affinity. The `murmur2_random` partitioner is pinned in [`crate::config`] (key design
//! point 1) — this module only supplies the key.

use anyhow::{Context, Result};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use common_liveness::SyncLivenessReporter;
use rdkafka::producer::FutureProducer;

use crate::event::{partition_key, CohortStreamEvent};

/// No-op liveness reporter for the producer's rdkafka client context.
///
/// The producer is driven entirely by the consumer loop; if it stalls, the consumer's
/// `forward().await` blocks and the *consumer* — which owns the liveness deadline — stops
/// heartbeating, tripping the stall detector. Feeding the producer's background stats
/// callback into the consumer's health instead would mask exactly that stall, so the
/// producer gets its own always-healthy sink.
#[derive(Clone, Copy)]
struct AlwaysHealthy;

impl SyncLivenessReporter for AlwaysHealthy {
    fn report_healthy(&self) {}
    fn report_unhealthy(&self) {}
}

/// Owns the `cohort_stream_events` producer and the canonical re-key.
pub struct CohortStreamProducer {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl CohortStreamProducer {
    /// Build the producer and verify broker connectivity (`create_kafka_producer` pings for
    /// metadata before returning).
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_stream_events producer")?;
        Ok(Self { producer, topic })
    }

    /// Produce every envelope to `cohort_stream_events`, keyed by `partition_key(team_id,
    /// person_id)`, and await all acks. Results are returned in input order so the caller can
    /// gate offset commits on full success (TDD at-least-once ordering, key design point 2).
    pub async fn forward(
        &self,
        events: Vec<CohortStreamEvent>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer,
            &self.topic,
            |event: &CohortStreamEvent| Some(partition_key(event.team_id, &event.person_id)),
            |_| None,
            events,
        )
        .await
    }
}
