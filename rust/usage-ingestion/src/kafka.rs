use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka::kafka_producer::KafkaContext;
use common_liveness::SyncLivenessReporter;
use futures::{stream, StreamExt, TryStreamExt};
use prost::Message;
use rdkafka::consumer::{CommitMode, Consumer, ConsumerContext, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::{Header, OwnedHeaders, OwnedMessage};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, ClientContext, Message as KafkaMessage, Offset, TopicPartitionList};
use usage_ingestion_proto::usage_ingestion::v1::IngestBillingUsageRequest;

use crate::service::{ProcessingError, UsageIngestionService};

#[derive(Clone, Copy)]
pub struct KafkaBatchConfig {
    pub max_messages: usize,
    pub max_wait: Duration,
    pub concurrency: usize,
}

pub struct KafkaUsageIngestion {
    consumer: StreamConsumer<KafkaConsumerContext>,
    dead_letter_producer: FutureProducer<KafkaContext>,
    dead_letter_topic: String,
    service: Arc<UsageIngestionService>,
    batch: KafkaBatchConfig,
}

struct KafkaConsumerContext {
    liveness: Arc<dyn SyncLivenessReporter>,
}

impl KafkaConsumerContext {
    fn new(liveness: impl SyncLivenessReporter + Clone + 'static) -> Self {
        Self {
            liveness: Arc::new(liveness),
        }
    }
}

impl ClientContext for KafkaConsumerContext {
    fn stats(&self, stats: rdkafka::Statistics) {
        if stats.brokers.values().any(|broker| broker.state == "UP") {
            self.liveness.report_healthy();
        } else {
            self.liveness.report_unhealthy();
        }
    }
}

impl ConsumerContext for KafkaConsumerContext {}

impl KafkaUsageIngestion {
    pub fn new(
        config: &ClientConfig,
        input_topic: &str,
        dead_letter_producer: FutureProducer<KafkaContext>,
        dead_letter_topic: String,
        service: Arc<UsageIngestionService>,
        batch: KafkaBatchConfig,
        liveness: impl SyncLivenessReporter + Clone + 'static,
    ) -> Result<Self, KafkaUsageIngestionError> {
        let consumer: StreamConsumer<KafkaConsumerContext> =
            config.create_with_context(KafkaConsumerContext::new(liveness.clone()))?;
        verify_topic(&consumer, input_topic)?;
        // A missing dead-letter topic would otherwise fail every dead-letter send, which
        // replays the same batch forever without ever committing.
        verify_topic(&consumer, &dead_letter_topic)?;
        consumer.subscribe(&[input_topic])?;
        liveness.report_healthy();
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
            if let Err(error) = self
                .consumer
                .commit(&batch_offsets(&messages)?, CommitMode::Sync)
            {
                if !is_rebalance_commit_error(&error) {
                    return Err(error.into());
                }
                // A rebalance mid-batch revokes partitions before their commit lands. The new
                // owner replays them, which is safe under idempotency. Failing here would tear
                // the consumer down, which triggers another rebalance, and so on in a storm.
                tracing::warn!(error = %error, "skipped a batch commit interrupted by a rebalance");
                metrics::counter!("usage_ingestion_kafka_commits_skipped_total").increment(1);
                continue;
            }
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

#[allow(clippy::too_many_arguments)]
pub async fn run_supervised(
    config: &ClientConfig,
    input_topic: &str,
    dead_letter_producer: FutureProducer<KafkaContext>,
    dead_letter_topic: &str,
    service: Arc<UsageIngestionService>,
    batch: KafkaBatchConfig,
    max_backoff: Duration,
    liveness: impl SyncLivenessReporter + Clone + 'static,
) {
    let mut backoff = Duration::from_secs(1).min(max_backoff);
    loop {
        let started = Instant::now();
        let result = match KafkaUsageIngestion::new(
            config,
            input_topic,
            dead_letter_producer.clone(),
            dead_letter_topic.to_string(),
            Arc::clone(&service),
            batch,
            liveness.clone(),
        ) {
            Ok(transport) => transport.run().await,
            Err(error) => Err(error),
        };

        liveness.report_unhealthy();

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

fn verify_topic(
    consumer: &StreamConsumer<KafkaConsumerContext>,
    topic: &str,
) -> Result<(), KafkaUsageIngestionError> {
    let metadata = consumer.fetch_metadata(Some(topic), Duration::from_secs(10))?;
    let topic_metadata = metadata
        .topics()
        .iter()
        .find(|candidate| candidate.name() == topic)
        .ok_or_else(|| KafkaUsageIngestionError::Topic(format!("{topic} is missing")))?;
    if let Some(error) = topic_metadata.error() {
        return Err(KafkaUsageIngestionError::Topic(format!(
            "broker returned {error:?} for {topic}"
        )));
    }
    if topic_metadata.partitions().is_empty() {
        return Err(KafkaUsageIngestionError::Topic(format!(
            "{topic} has no partitions"
        )));
    }
    Ok(())
}

fn is_rebalance_commit_error(error: &KafkaError) -> bool {
    matches!(
        error.rdkafka_error_code(),
        Some(
            RDKafkaErrorCode::RebalanceInProgress
                | RDKafkaErrorCode::IllegalGeneration
                | RDKafkaErrorCode::UnknownMemberId
        )
    )
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
    #[error("Kafka topic is unavailable: {0}")]
    Topic(String),
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};

    use rdkafka::message::OwnedMessage;
    use rdkafka::statistics::Broker;
    use rdkafka::Timestamp;

    use super::*;

    #[derive(Clone, Default)]
    struct TestLiveness(Arc<AtomicBool>);

    impl SyncLivenessReporter for TestLiveness {
        fn report_healthy(&self) {
            self.0.store(true, Ordering::Relaxed);
        }

        fn report_unhealthy(&self) {
            self.0.store(false, Ordering::Relaxed);
        }
    }

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

    #[test]
    fn only_rebalance_class_commit_errors_are_skipped() {
        for code in [
            RDKafkaErrorCode::RebalanceInProgress,
            RDKafkaErrorCode::IllegalGeneration,
            RDKafkaErrorCode::UnknownMemberId,
        ] {
            assert!(is_rebalance_commit_error(&KafkaError::ConsumerCommit(code)));
        }
        assert!(!is_rebalance_commit_error(&KafkaError::ConsumerCommit(
            RDKafkaErrorCode::BrokerTransportFailure
        )));
    }

    #[test]
    fn consumer_health_follows_broker_connectivity() {
        let liveness = TestLiveness::default();
        let context = KafkaConsumerContext::new(liveness.clone());

        context.stats(rdkafka::Statistics::default());
        assert!(!liveness.0.load(Ordering::Relaxed));

        let mut stats = rdkafka::Statistics::default();
        stats.brokers.insert(
            "broker".to_string(),
            Broker {
                state: "UP".to_string(),
                ..Default::default()
            },
        );
        context.stats(stats);
        assert!(liveness.0.load(Ordering::Relaxed));
    }
}
