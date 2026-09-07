use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::{stream, StreamExt, TryStreamExt};
use prost::Message;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::{Header, OwnedHeaders, OwnedMessage};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Message as KafkaMessage, Offset, TopicPartitionList};
use usage_ingestion_proto::usage_ingestion::v1::IngestBillingUsageRequest;

use crate::service::{ProcessingError, UsageIngestionService};

#[derive(Clone, Copy)]
pub struct KafkaBatchConfig {
    pub max_messages: usize,
    pub max_wait: Duration,
    pub concurrency: usize,
}

pub struct KafkaUsageIngestion {
    consumer: StreamConsumer,
    dead_letter_producer: FutureProducer,
    dead_letter_topic: String,
    service: Arc<UsageIngestionService>,
    batch: KafkaBatchConfig,
}

impl KafkaUsageIngestion {
    pub fn new(
        config: &ClientConfig,
        input_topic: &str,
        dead_letter_topic: String,
        service: Arc<UsageIngestionService>,
        batch: KafkaBatchConfig,
    ) -> Result<Self, KafkaError> {
        let consumer: StreamConsumer = config.create()?;
        consumer.subscribe(&[input_topic])?;
        let dead_letter_producer = config.create()?;
        Ok(Self {
            consumer,
            dead_letter_producer,
            dead_letter_topic,
            service,
            batch,
        })
    }

    pub async fn run(&self) -> Result<(), KafkaUsageIngestionError> {
        loop {
            let messages = self.receive_batch().await?;

            stream::iter(&messages)
                .map(Ok)
                .try_for_each_concurrent(self.batch.concurrency, |message| {
                    self.process_message(message)
                })
                .await?;

            // A batch is all-or-nothing: failures leave every offset uncommitted. Successful
            // output may be replayed, which is safe because usage record IDs are idempotent.
            self.consumer
                .commit(&batch_offsets(&messages)?, CommitMode::Sync)?;
            metrics::counter!("usage_ingestion_kafka_commits_total").increment(1);
        }
    }

    async fn receive_batch(&self) -> Result<Vec<OwnedMessage>, KafkaError> {
        let mut messages = vec![self.consumer.recv().await?.detach()];
        let deadline = tokio::time::sleep(self.batch.max_wait);
        tokio::pin!(deadline);

        while messages.len() < self.batch.max_messages {
            tokio::select! {
                _ = &mut deadline => break,
                message = self.consumer.recv() => messages.push(message?.detach()),
            }
        }

        metrics::histogram!("usage_ingestion_kafka_batch_size").record(messages.len() as f64);
        Ok(messages)
    }

    async fn process_message(
        &self,
        message: &OwnedMessage,
    ) -> Result<(), KafkaUsageIngestionError> {
        let request = message
            .payload()
            .ok_or_else(|| prost::DecodeError::new("empty Kafka payload"))
            .and_then(IngestBillingUsageRequest::decode);

        match request {
            Ok(request) => {
                let record_count = request.records.len();
                match self.service.process(request).await {
                    Ok(response) if response.accepted_record_ids.len() == record_count => {
                        metrics::counter!(
                            "usage_ingestion_kafka_messages_total",
                            "outcome" => "processed"
                        )
                        .increment(1);
                        Ok(())
                    }
                    Ok(_) => {
                        let reason = "one or more usage records were rejected";
                        self.dead_letter(message, reason.to_string()).await?;
                        tracing::warn!(
                            partition = message.partition(),
                            offset = message.offset(),
                            "sent partially rejected usage ingestion message to the dead-letter topic"
                        );
                        Ok(())
                    }
                    Err(error) if error.is_retryable() => Err(error.into()),
                    Err(error) => {
                        self.dead_letter(message, error.to_string()).await?;
                        tracing::warn!(
                            error = %error,
                            partition = message.partition(),
                            offset = message.offset(),
                            "sent rejected usage ingestion message to the dead-letter topic"
                        );
                        Ok(())
                    }
                }
            }
            Err(error) => {
                self.dead_letter(message, error.to_string()).await?;
                tracing::warn!(
                    error = %error,
                    partition = message.partition(),
                    offset = message.offset(),
                    "sent malformed usage ingestion message to the dead-letter topic"
                );
                Ok(())
            }
        }
    }

    async fn dead_letter(
        &self,
        message: &OwnedMessage,
        reason: String,
    ) -> Result<(), KafkaUsageIngestionError> {
        let partition = message.partition().to_string();
        let offset = message.offset().to_string();
        let headers = OwnedHeaders::new()
            .insert(Header {
                key: "usage-ingestion-source-topic",
                value: Some(message.topic()),
            })
            .insert(Header {
                key: "usage-ingestion-source-partition",
                value: Some(&partition),
            })
            .insert(Header {
                key: "usage-ingestion-source-offset",
                value: Some(&offset),
            })
            .insert(Header {
                key: "usage-ingestion-error",
                value: Some(&reason),
            });
        let mut record = FutureRecord::to(&self.dead_letter_topic)
            .payload(message.payload().unwrap_or_default())
            .headers(headers);
        if let Some(key) = message.key() {
            record = record.key(key);
        }
        self.dead_letter_producer
            .send(record, Timeout::After(Duration::from_secs(10)))
            .await
            .map_err(|(error, _)| error)?;
        metrics::counter!(
            "usage_ingestion_kafka_messages_total",
            "outcome" => "dead_lettered"
        )
        .increment(1);
        Ok(())
    }
}

pub async fn run_supervised(
    config: &ClientConfig,
    input_topic: &str,
    dead_letter_topic: &str,
    service: Arc<UsageIngestionService>,
    batch: KafkaBatchConfig,
    max_backoff: Duration,
) {
    let mut backoff = Duration::from_secs(1).min(max_backoff);
    loop {
        let started = Instant::now();
        let result = match KafkaUsageIngestion::new(
            config,
            input_topic,
            dead_letter_topic.to_string(),
            Arc::clone(&service),
            batch,
        ) {
            Ok(transport) => transport.run().await,
            Err(error) => Err(error.into()),
        };

        tracing::error!(
            error = %result.expect_err("the Kafka consumer only exits on failure"),
            retry_in_ms = backoff.as_millis(),
            "usage ingestion Kafka consumer failed; restarting it"
        );
        metrics::counter!("usage_ingestion_kafka_restarts_total").increment(1);

        if started.elapsed() >= max_backoff {
            backoff = Duration::from_secs(1).min(max_backoff);
        }
        tokio::time::sleep(backoff).await;
        backoff = backoff.saturating_mul(2).min(max_backoff);
    }
}

fn batch_offsets(messages: &[OwnedMessage]) -> Result<TopicPartitionList, KafkaError> {
    let mut offsets = BTreeMap::new();
    for message in messages {
        offsets
            .entry((message.topic().to_string(), message.partition()))
            .and_modify(|offset: &mut i64| *offset = (*offset).max(message.offset() + 1))
            .or_insert(message.offset() + 1);
    }

    let mut partitions = TopicPartitionList::with_capacity(offsets.len());
    for ((topic, partition), offset) in offsets {
        partitions.add_partition_offset(&topic, partition, Offset::Offset(offset))?;
    }
    Ok(partitions)
}

#[derive(Debug, thiserror::Error)]
pub enum KafkaUsageIngestionError {
    #[error("Kafka transport failed: {0}")]
    Kafka(#[from] KafkaError),
    #[error("usage processing failed before the input offsets were committed: {0}")]
    Processing(#[from] ProcessingError),
}

#[cfg(test)]
mod tests {
    use rdkafka::message::OwnedMessage;
    use rdkafka::Timestamp;

    use super::*;

    fn message(topic: &str, partition: i32, offset: i64) -> OwnedMessage {
        OwnedMessage::new(
            None,
            None,
            topic.to_string(),
            Timestamp::NotAvailable,
            partition,
            offset,
            None,
        )
    }

    #[test]
    fn commits_only_the_high_water_mark_for_each_partition() {
        let offsets = batch_offsets(&[
            message("usage", 0, 4),
            message("usage", 1, 8),
            message("usage", 0, 6),
            message("usage", 1, 7),
        ])
        .unwrap();

        assert_eq!(
            offsets.find_partition("usage", 0).unwrap().offset(),
            Offset::Offset(7)
        );
        assert_eq!(
            offsets.find_partition("usage", 1).unwrap().offset(),
            Offset::Offset(9)
        );
    }
}
