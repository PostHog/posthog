use std::sync::Arc;
use std::time::Duration;

use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::{Headers, Message};
use rdkafka::ClientConfig;
use tokio::time::timeout;
use tracing::{error, info, warn};

use crate::config::Config;
use crate::error::IngestionError;
use crate::router::MessageRouter;
use crate::transport::IngestionTransport;
use crate::types::SerializedMessage;

pub struct IngestionConsumerLoop {
    consumer: StreamConsumer,
    router: MessageRouter,
    transport: Arc<dyn IngestionTransport>,
    targets: Vec<String>,
    batch_size: usize,
    batch_timeout: Duration,
}

impl IngestionConsumerLoop {
    pub fn new(
        config: &Config,
        transport: Arc<dyn IngestionTransport>,
    ) -> Result<Self, IngestionError> {
        let targets = config.target_addresses();
        let router = MessageRouter::new(targets.len());

        let consumer: StreamConsumer = ClientConfig::new()
            .set("group.id", &config.kafka_group_id)
            .set("bootstrap.servers", &config.kafka.kafka_hosts)
            .set("enable.auto.commit", "false")
            .set("auto.offset.reset", "latest")
            .set("fetch.min.bytes", "1")
            .set("fetch.wait.max.ms", "100")
            .create()?;

        consumer.subscribe(&[&config.kafka_topic])?;

        info!(
            topic = config.kafka_topic,
            group_id = config.kafka_group_id,
            targets = targets.len(),
            "Kafka consumer subscribed"
        );

        Ok(Self {
            consumer,
            router,
            transport,
            targets,
            batch_size: config.batch_size,
            batch_timeout: Duration::from_millis(config.batch_timeout_ms),
        })
    }

    pub async fn run(&self, shutdown: tokio::sync::watch::Receiver<bool>) -> Result<(), IngestionError> {
        info!("Starting consumer loop");

        loop {
            if *shutdown.borrow() {
                info!("Shutdown signal received, stopping consumer loop");
                break;
            }

            match self.process_batch().await {
                Ok(count) => {
                    if count > 0 {
                        metrics::counter!("ingestion_consumer_batches_processed").increment(1);
                        metrics::counter!("ingestion_consumer_messages_processed")
                            .increment(count as u64);
                    }
                }
                Err(e) => {
                    error!(error = %e, "batch processing failed, will retry");
                    metrics::counter!("ingestion_consumer_batch_errors").increment(1);
                    tokio::time::sleep(Duration::from_secs(1)).await;
                }
            }
        }

        Ok(())
    }

    async fn process_batch(&self) -> Result<usize, IngestionError> {
        let messages = self.collect_batch().await?;

        if messages.is_empty() {
            return Ok(0);
        }

        let count = messages.len();
        let groups = self.router.route_batch(messages);

        // Send to all targets concurrently
        let mut send_futures = Vec::new();
        for (target_idx, batch) in groups {
            let target = &self.targets[target_idx];
            let transport = self.transport.clone();
            let target_owned = target.clone();
            send_futures.push(async move {
                transport.send_batch(&target_owned, batch).await
            });
        }

        let results = futures::future::join_all(send_futures).await;

        // Check for errors
        let mut had_error = false;
        for result in &results {
            if let Err(e) = result {
                error!(error = %e, "failed to send batch to target");
                had_error = true;
            }
        }

        if had_error {
            return Err(IngestionError::Transport {
                target: "multiple".to_string(),
                source: anyhow::anyhow!("one or more targets failed"),
            });
        }

        // All succeeded - commit offsets
        if let Err(e) = self.consumer.commit_consumer_state(CommitMode::Async) {
            warn!(error = %e, "failed to commit offsets");
        }

        Ok(count)
    }

    async fn collect_batch(&self) -> Result<Vec<SerializedMessage>, IngestionError> {
        let mut messages = Vec::with_capacity(self.batch_size);

        for _ in 0..self.batch_size {
            let recv = timeout(self.batch_timeout, self.consumer.recv()).await;

            match recv {
                Ok(Ok(msg)) => {
                    let serialized = serialize_borrowed_message(&msg);
                    messages.push(serialized);
                }
                Ok(Err(e)) => {
                    warn!(error = %e, "kafka recv error");
                    break;
                }
                Err(_) => {
                    // Timeout - return what we have
                    break;
                }
            }
        }

        Ok(messages)
    }
}

fn serialize_borrowed_message(msg: &rdkafka::message::BorrowedMessage<'_>) -> SerializedMessage {
    let headers: Vec<(String, Vec<u8>)> = msg
        .headers()
        .map(|hdrs| {
            hdrs.iter()
                .filter_map(|header| {
                    header.value.map(|v| (header.key.to_string(), v.to_vec()))
                })
                .collect()
        })
        .unwrap_or_default();

    SerializedMessage::from_kafka_message(
        msg.topic(),
        msg.partition(),
        msg.offset(),
        msg.timestamp().to_millis(),
        msg.key(),
        msg.payload(),
        headers,
    )
}
