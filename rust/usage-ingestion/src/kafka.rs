use std::sync::Arc;

use prost::Message;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::{ClientConfig, Message as KafkaMessage};
use usage_ingestion_proto::usage_ingestion::v1::IngestBillingUsageRequest;

use crate::service::{ProcessingError, UsageIngestionService};

pub struct KafkaUsageIngestion {
    consumer: StreamConsumer,
    service: Arc<UsageIngestionService>,
}

impl KafkaUsageIngestion {
    pub fn new(
        config: &ClientConfig,
        topic: &str,
        service: Arc<UsageIngestionService>,
    ) -> Result<Self, KafkaError> {
        let consumer: StreamConsumer = config.create()?;
        consumer.subscribe(&[topic])?;
        Ok(Self { consumer, service })
    }

    pub async fn run(&self) -> Result<(), KafkaUsageIngestionError> {
        loop {
            let message = loop {
                match self.consumer.recv().await {
                    Ok(message) => break message,
                    Err(KafkaError::MessageConsumption(
                        RDKafkaErrorCode::UnknownTopicOrPartition,
                    )) => {
                        tracing::warn!("usage ingestion input topic is not available yet");
                        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                    }
                    Err(error) => return Err(error.into()),
                }
            };
            let request = match message
                .payload()
                .ok_or_else(|| prost::DecodeError::new("empty Kafka payload"))
                .and_then(IngestBillingUsageRequest::decode)
            {
                Ok(request) => request,
                Err(error) => {
                    tracing::warn!(
                        error = %error,
                        partition = message.partition(),
                        offset = message.offset(),
                        "dropping malformed usage ingestion message"
                    );
                    metrics::counter!(
                        "usage_ingestion_kafka_messages_total",
                        "outcome" => "malformed"
                    )
                    .increment(1);
                    self.consumer.commit_message(&message, CommitMode::Sync)?;
                    continue;
                }
            };

            match self.service.process(request).await {
                Ok(_) => {
                    metrics::counter!(
                        "usage_ingestion_kafka_messages_total",
                        "outcome" => "processed"
                    )
                    .increment(1);
                }
                Err(error) if error.is_retryable() => return Err(error.into()),
                Err(error) => {
                    tracing::warn!(
                        error = %error,
                        partition = message.partition(),
                        offset = message.offset(),
                        "dropping rejected usage ingestion message"
                    );
                    metrics::counter!(
                        "usage_ingestion_kafka_messages_total",
                        "outcome" => "rejected"
                    )
                    .increment(1);
                }
            }

            self.consumer.commit_message(&message, CommitMode::Sync)?;
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum KafkaUsageIngestionError {
    #[error("Kafka consumer failed: {0}")]
    Kafka(#[from] KafkaError),
    #[error("usage processing failed before the input offset was committed: {0}")]
    Processing(#[from] ProcessingError),
}
