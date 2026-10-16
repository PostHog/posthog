//! Where a drained batch goes. The drain commits its outbox write-back only
//! after [`PublishSink::send`] returns `Ok`, so a sink must not report
//! success before every message is acked; tests substitute recording and
//! failing sinks for the Kafka one.

use std::time::Duration;

use async_trait::async_trait;
use common_kafka::kafka_producer::{send_iter_to_kafka, KafkaContext};
use rdkafka::producer::FutureProducer;

use crate::publish::messages::DistinctIdRow;

const PUBLISH_MESSAGES_TOTAL: &str = "personhog_lifecycle_publish_messages_total";

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct PublishBatch {
    pub distinct_id_rows: Vec<DistinctIdRow>,
}

impl PublishBatch {
    pub fn is_empty(&self) -> bool {
        self.distinct_id_rows.is_empty()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum PublishError {
    #[error("kafka produce failed: {0}")]
    Kafka(String),
    #[error("kafka produce did not complete within {0:?}")]
    Timeout(Duration),
}

#[async_trait]
pub trait PublishSink: Send + Sync {
    /// Resolves only after every message in the batch is acked. An error
    /// means none of them may be treated as published; some may still
    /// arrive later, which every consumer of these topics absorbs.
    async fn send(&self, batch: &PublishBatch) -> Result<(), PublishError>;
}

pub struct KafkaSink {
    producer: FutureProducer<KafkaContext>,
    distinct_id_topic: String,
    produce_timeout: Duration,
}

impl KafkaSink {
    pub fn new(
        producer: FutureProducer<KafkaContext>,
        distinct_id_topic: String,
        produce_timeout: Duration,
    ) -> Self {
        Self {
            producer,
            distinct_id_topic,
            produce_timeout,
        }
    }
}

#[async_trait]
impl PublishSink for KafkaSink {
    async fn send(&self, batch: &PublishBatch) -> Result<(), PublishError> {
        if batch.is_empty() {
            return Ok(());
        }
        // Null keys, like the Node producer: the consumers order by
        // `version`, not by partition.
        let sent = tokio::time::timeout(
            self.produce_timeout,
            send_iter_to_kafka(
                &self.producer,
                &self.distinct_id_topic,
                &batch.distinct_id_rows,
            ),
        )
        .await
        .map_err(|_| PublishError::Timeout(self.produce_timeout))?;
        let failed = sent.iter().filter(|r| r.is_err()).count();
        if let Some(Err(first)) = sent.iter().find(|r| r.is_err()) {
            return Err(PublishError::Kafka(format!(
                "{failed} of {} messages failed; first error: {first}",
                sent.len()
            )));
        }
        common_metrics::inc(
            PUBLISH_MESSAGES_TOTAL,
            &[("topic".to_string(), self.distinct_id_topic.clone())],
            sent.len() as u64,
        );
        Ok(())
    }
}
