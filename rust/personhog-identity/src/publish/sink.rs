//! Where a drained batch goes. The drain commits its outbox write-back only
//! after [`PublishSink::send`] returns `Ok`, so a sink must not report
//! success before every message is acked; tests substitute recording and
//! failing sinks for the Kafka one.

use std::time::Duration;

use async_trait::async_trait;
use common_kafka::kafka_producer::{send_iter_to_kafka, send_keyed_iter_to_kafka, KafkaContext};
use rdkafka::producer::FutureProducer;

use crate::publish::messages::{DistinctIdRow, PersonMergeEvent};

const PUBLISH_MESSAGES_TOTAL: &str = "personhog_lifecycle_publish_messages_total";

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct PublishBatch {
    pub distinct_id_rows: Vec<DistinctIdRow>,
    pub merge_events: Vec<PersonMergeEvent>,
}

impl PublishBatch {
    pub fn is_empty(&self) -> bool {
        self.distinct_id_rows.is_empty() && self.merge_events.is_empty()
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

/// The Kafka sink. Merge events are keyed and the producer places them with
/// the partitioner [`crate::publish::config::MURMUR2_RANDOM`] pins.
pub struct KafkaSink {
    producer: FutureProducer<KafkaContext>,
    distinct_id_topic: String,
    /// `None` while merge events are disabled; a batch that carries one
    /// anyway is a configuration error the sink refuses rather than drops.
    merge_events_topic: Option<String>,
    produce_timeout: Duration,
}

impl KafkaSink {
    pub fn new(
        producer: FutureProducer<KafkaContext>,
        distinct_id_topic: String,
        merge_events_topic: Option<String>,
        produce_timeout: Duration,
    ) -> Self {
        Self {
            producer,
            distinct_id_topic,
            merge_events_topic,
            produce_timeout,
        }
    }

    /// Both topics are produced at once: the drain commits only after both
    /// are acked, so neither the order nor a success on one side alone
    /// means anything.
    async fn produce(&self, batch: &PublishBatch) -> Result<(), PublishError> {
        let (rows, events) = tokio::join!(self.produce_rows(batch), self.produce_events(batch));
        rows.and(events)
    }

    async fn produce_rows(&self, batch: &PublishBatch) -> Result<(), PublishError> {
        if batch.distinct_id_rows.is_empty() {
            return Ok(());
        }
        // Null keys, like the Node producer: the consumers order by
        // `version`, not by partition.
        let sent = send_iter_to_kafka(
            &self.producer,
            &self.distinct_id_topic,
            &batch.distinct_id_rows,
        )
        .await;
        settle(&self.distinct_id_topic, "distinct id", &sent)
    }

    async fn produce_events(&self, batch: &PublishBatch) -> Result<(), PublishError> {
        if batch.merge_events.is_empty() {
            return Ok(());
        }
        let Some(topic) = &self.merge_events_topic else {
            return Err(PublishError::Kafka(
                "merge events in a batch but no merge events topic is configured".to_string(),
            ));
        };
        let sent = send_keyed_iter_to_kafka(
            &self.producer,
            topic,
            |event: &&PersonMergeEvent| Some(event.key()),
            &batch.merge_events,
        )
        .await;
        settle(topic, "merge event", &sent)
    }
}

fn settle<E: std::fmt::Display>(
    topic: &str,
    what: &str,
    sent: &[Result<(), E>],
) -> Result<(), PublishError> {
    let failed = sent.iter().filter(|r| r.is_err()).count();
    if let Some(Err(first)) = sent.iter().find(|r| r.is_err()) {
        return Err(PublishError::Kafka(format!(
            "{failed} of {} {what} messages failed; first error: {first}",
            sent.len()
        )));
    }
    common_metrics::inc(
        PUBLISH_MESSAGES_TOTAL,
        &[("topic".to_string(), topic.to_string())],
        sent.len() as u64,
    );
    Ok(())
}

#[async_trait]
impl PublishSink for KafkaSink {
    async fn send(&self, batch: &PublishBatch) -> Result<(), PublishError> {
        if batch.is_empty() {
            return Ok(());
        }
        tokio::time::timeout(self.produce_timeout, self.produce(batch))
            .await
            .map_err(|_| PublishError::Timeout(self.produce_timeout))?
    }
}
