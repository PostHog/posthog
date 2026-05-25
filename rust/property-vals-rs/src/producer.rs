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
