//! Re-key producer for `cohort_stream_seed_events`: cross-partition-merged tiles are re-produced
//! to the survivor's partition, keyed exactly as the seeder keys them.

use anyhow::{Context, Result};
use async_trait::async_trait;
use cohort_core::seed::SeedTile;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext, KafkaProduceError,
};
use rdkafka::producer::FutureProducer;

use crate::producer::kafka::AlwaysHealthy;
use crate::producer::merge::Capture;

#[async_trait]
pub trait SeedTileSink: Send + Sync {
    async fn produce(&self, tiles: Vec<SeedTile>) -> Vec<Result<(), KafkaProduceError>>;
}

pub struct KafkaSeedTileSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaSeedTileSink {
    pub async fn new(kafka_config: &KafkaConfig, topic: String) -> Result<Self> {
        let producer = create_kafka_producer(kafka_config, AlwaysHealthy)
            .await
            .context("creating cohort_stream_seed_events re-key producer")?;
        Ok(Self { producer, topic })
    }
}

#[async_trait]
impl SeedTileSink for KafkaSeedTileSink {
    async fn produce(&self, tiles: Vec<SeedTile>) -> Vec<Result<(), KafkaProduceError>> {
        send_keyed_iter_to_kafka_with_headers(
            &self.producer,
            &self.topic,
            |tile| Some(tile.partition_key()),
            |_| None,
            tiles,
        )
        .await
    }
}

/// Inert sink for gate-off deploys: a produce is a coding error made loud, not a silent drop.
pub struct NoopSeedTileSink;

#[async_trait]
impl SeedTileSink for NoopSeedTileSink {
    async fn produce(&self, tiles: Vec<SeedTile>) -> Vec<Result<(), KafkaProduceError>> {
        tiles
            .into_iter()
            .map(|_| Err(KafkaProduceError::KafkaProduceCanceled))
            .collect()
    }
}

pub struct CaptureSeedTileSink(Capture<SeedTile>);

impl CaptureSeedTileSink {
    pub fn new() -> Self {
        Self(Capture::default())
    }

    pub fn failing_first(n: usize) -> Self {
        Self(Capture::failing_first(n))
    }

    pub fn failing_always() -> Self {
        Self(Capture::failing_always())
    }

    pub fn tiles(&self) -> Vec<SeedTile> {
        self.0.recorded()
    }
}

impl Default for CaptureSeedTileSink {
    fn default() -> Self {
        Self::new()
    }
}

impl Clone for CaptureSeedTileSink {
    fn clone(&self) -> Self {
        Self(self.0.clone())
    }
}

#[async_trait]
impl SeedTileSink for CaptureSeedTileSink {
    async fn produce(&self, tiles: Vec<SeedTile>) -> Vec<Result<(), KafkaProduceError>> {
        self.0.produce(tiles)
    }
}
