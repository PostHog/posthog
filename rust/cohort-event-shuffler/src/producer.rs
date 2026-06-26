//! Kafka producer for `cohort_stream_events`. The `murmur2_random` partitioner is pinned in
//! [`crate::config`]; this module only supplies the [`partition_key`].

use anyhow::{Context, Result};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use common_liveness::SyncLivenessReporter;
use rdkafka::producer::FutureProducer;

use crate::event::{partition_key, CohortStreamEvent};

/// A producer stall blocks the consumer's `forward().await`, which stops the consumer (owner of
/// the liveness deadline) from heartbeating and trips the stall detector. So the producer reports
/// always-healthy rather than feeding its stats into the consumer's health and masking that stall.
#[derive(Clone, Copy)]
struct AlwaysHealthy;

impl SyncLivenessReporter for AlwaysHealthy {
    fn report_healthy(&self) {}
    fn report_unhealthy(&self) {}
}

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

    /// Produces and awaits all acks. Results are returned in input order so the caller can gate
    /// offset commits on full success.
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
