use std::time::Duration;

use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_consumer::SingleTopicConsumer;
use common_kafka::kafka_producer::{send_keyed_iter_to_kafka, KafkaProduceError};
use common_kafka::transaction::TransactionalProducer;
use rdkafka::error::KafkaError;
use rdkafka::producer::Producer as RdkafkaProducer;
use rdkafka::TopicPartitionList;
use thiserror::Error;
use tracing::{error, warn};

use crate::types::{PropertyType, TupleKey};

#[derive(serde::Serialize)]
struct Outgoing<'a> {
    team_id: i64,
    property_type: PropertyType,
    property_key: &'a str,
    property_value: &'a str,
    property_count: u64,
}

#[derive(Debug, Clone)]
pub struct OffsetSnapshot {
    pub topic: String,
    pub partition: i32,
    pub offset: i64,
}

#[derive(Debug, Error)]
pub enum ProduceError {
    #[error("kafka produce timed out after {0:?}")]
    Timeout(Duration),
    #[error("{failed}/{total} records failed delivery")]
    PartialFailure { failed: usize, total: usize },
    #[error("transaction begin failed: {0}")]
    Begin(String),
    #[error("offset commit to transaction failed: {0}")]
    OffsetCommit(String),
    #[error("transaction commit failed: {0}")]
    Commit(String),
}

/// Atomically commits one flush window: produce all aggregated tuples to the
/// output topic AND commit the input partition offsets to the consumer
/// group, both inside a single Kafka transaction. Either both writes are
/// durable or neither happens.
///
/// `&mut self` because rdkafka allows only one outstanding transaction per
/// `transactional.id`. With one worker per pod (the deployed shape), this
/// matches the only producer instance.
#[async_trait]
pub trait Producer: Send {
    async fn produce_and_commit(
        &mut self,
        items: Vec<(TupleKey, u64)>,
        offsets: Vec<OffsetSnapshot>,
    ) -> Result<(), ProduceError>;
}

/// Real producer: wraps a Kafka transactional producer and the consumer it
/// belongs to (needed for `ConsumerGroupMetadata` on every commit). Skips
/// the `KafkaTransaction` wrapper in common-kafka because we need to chain
/// `send_offsets_to_transaction` and `send_keyed_iter_to_kafka` from the
/// same inner FutureProducer reference, which the wrapper's borrow shape
/// disallows.
pub struct AggregatedProducer {
    inner: TransactionalProducer,
    output_topic: String,
    consumer: SingleTopicConsumer,
    transaction_timeout: Duration,
}

impl AggregatedProducer {
    pub fn new(
        kafka_config: &KafkaConfig,
        transactional_id: &str,
        output_topic: String,
        transaction_timeout: Duration,
        consumer: SingleTopicConsumer,
    ) -> Result<Self, KafkaError> {
        let inner = TransactionalProducer::from_config(
            kafka_config,
            transactional_id,
            transaction_timeout,
        )?;
        Ok(Self {
            inner,
            output_topic,
            consumer,
            transaction_timeout,
        })
    }
}

#[async_trait]
impl Producer for AggregatedProducer {
    async fn produce_and_commit(
        &mut self,
        items: Vec<(TupleKey, u64)>,
        offsets: Vec<OffsetSnapshot>,
    ) -> Result<(), ProduceError> {
        if items.is_empty() && offsets.is_empty() {
            return Ok(());
        }

        let metadata = self.consumer.metadata();
        let producer = self.inner.inner();

        producer
            .begin_transaction()
            .map_err(|e| ProduceError::Begin(e.to_string()))?;

        let total = items.len();
        if !items.is_empty() {
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
                producer,
                &self.output_topic,
                |m| Some(m.team_id.to_string()),
                messages,
            );

            let results = match tokio::time::timeout(self.transaction_timeout, send_fut).await {
                Ok(r) => r,
                Err(_) => {
                    abort_logged(producer, self.transaction_timeout);
                    return Err(ProduceError::Timeout(self.transaction_timeout));
                }
            };

            let failed = results
                .iter()
                .filter(|r| matches!(r, Err(KafkaProduceError::KafkaProduceError { .. })))
                .count();
            if failed > 0 {
                abort_logged(producer, self.transaction_timeout);
                return Err(ProduceError::PartialFailure { failed, total });
            }
        }

        if !offsets.is_empty() {
            let tpl = build_topic_partition_list(&offsets);
            if let Err(e) =
                producer.send_offsets_to_transaction(&tpl, &metadata, self.transaction_timeout)
            {
                abort_logged(producer, self.transaction_timeout);
                return Err(ProduceError::OffsetCommit(e.to_string()));
            }
        }

        if let Err(e) = producer.commit_transaction(self.transaction_timeout) {
            abort_logged(producer, self.transaction_timeout);
            return Err(ProduceError::Commit(e.to_string()));
        }
        Ok(())
    }
}

fn abort_logged<C: rdkafka::ClientContext>(
    producer: &rdkafka::producer::FutureProducer<C>,
    timeout: Duration,
) {
    if let Err(e) = producer.abort_transaction(timeout) {
        error!(error = %e, "kafka abort_transaction failed");
    } else {
        warn!("kafka transaction aborted");
    }
}

/// Build a TopicPartitionList from offset snapshots. Per rdkafka's
/// `send_offsets_to_transaction` docs, the committed offset is "one greater
/// than the last processed message's offset", so we add 1 to each.
fn build_topic_partition_list(snapshots: &[OffsetSnapshot]) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    for s in snapshots {
        tpl.add_partition_offset(&s.topic, s.partition, rdkafka::Offset::Offset(s.offset + 1))
            .expect("TopicPartitionList::add_partition_offset is infallible for valid inputs");
    }
    tpl
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_tpl_adds_one_to_each_offset() {
        let snapshots = vec![
            OffsetSnapshot {
                topic: "t".into(),
                partition: 0,
                offset: 5,
            },
            OffsetSnapshot {
                topic: "t".into(),
                partition: 1,
                offset: 10,
            },
        ];
        let tpl = build_topic_partition_list(&snapshots);
        let elements = tpl.elements();
        assert_eq!(elements.len(), 2);
        let p0 = elements.iter().find(|e| e.partition() == 0).unwrap();
        let p1 = elements.iter().find(|e| e.partition() == 1).unwrap();
        assert!(matches!(p0.offset(), rdkafka::Offset::Offset(6)));
        assert!(matches!(p1.offset(), rdkafka::Offset::Offset(11)));
    }
}
