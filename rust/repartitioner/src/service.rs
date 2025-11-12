use anyhow::{Context, Result};
use common_kafka::{
    config::KafkaConfig,
    kafka_producer::{create_kafka_producer, KafkaContext},
};
use health::HealthRegistry;
use rdkafka::{
    consumer::{Consumer, StreamConsumer},
    message::{BorrowedHeaders, BorrowedMessage},
    producer::FutureRecord,
    ClientConfig, Message,
};
use std::time::Duration;
use tracing::{error, info};

use crate::config::Config;
use crate::repartitioners::compute_propdefs_v1_key;

pub struct RepartitionerService {
    config: Config,
    consumer: StreamConsumer,
    producer: rdkafka::producer::FutureProducer<KafkaContext>,
    health: HealthRegistry,
}

impl RepartitionerService {
    pub async fn new(config: Config, health: HealthRegistry) -> Result<Self> {
        let kafka_config = KafkaConfig {
            kafka_hosts: config.kafka_hosts.clone(),
            kafka_tls: config.kafka_tls,
            kafka_producer_linger_ms: config.kafka_producer_linger_ms,
            kafka_producer_queue_mib: config.kafka_producer_queue_mib,
            kafka_producer_queue_messages: config.kafka_producer_queue_messages,
            kafka_message_timeout_ms: config.kafka_message_timeout_ms,
            kafka_compression_codec: config.kafka_compression_codec.clone(),
        };

        // Create consumer directly to get raw messages
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("group.id", &config.kafka_consumer_group)
            .set("auto.offset.reset", &config.kafka_consumer_offset_reset)
            .set("enable.auto.offset.store", "false");

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }

        if config.kafka_consumer_auto_commit {
            client_config.set("enable.auto.commit", "true").set(
                "auto.commit.interval.ms",
                config.kafka_consumer_auto_commit_interval_ms.to_string(),
            );
        }

        let consumer: StreamConsumer = client_config
            .create()
            .context("Failed to create Kafka consumer")?;
        consumer
            .subscribe(&[&config.kafka_source_topic])
            .context("Failed to subscribe to topic")?;

        let health_handle = health
            .register("kafka_producer".to_string(), Duration::from_secs(30))
            .await;
        let producer = create_kafka_producer(&kafka_config, health_handle)
            .await
            .context("Failed to create Kafka producer")?;

        info!(
            "Repartitioner service initialized: consuming from '{}', producing to '{}'",
            config.kafka_source_topic, config.kafka_destination_topic
        );

        Ok(Self {
            config,
            consumer,
            producer,
            health,
        })
    }

    pub async fn run(&self) -> Result<()> {
        info!("Starting repartitioner service");

        let consumer_health = self
            .health
            .register("kafka_consumer".to_string(), Duration::from_secs(30))
            .await;
        consumer_health.report_healthy().await;

        loop {
            match self.consumer.recv().await {
                Ok(message) => {
                    if let Err(e) = self.process_message(&message).await {
                        error!("Failed to process message: {}", e);
                    } else {
                        consumer_health.report_healthy().await;
                    }
                }
                Err(e) => {
                    error!("Error receiving message: {}", e);
                    consumer_health
                        .report_status(health::ComponentStatus::Unhealthy)
                        .await;
                }
            }
        }
    }

    async fn process_message(&self, message: &BorrowedMessage<'_>) -> Result<()> {
        let payload = message.payload();
        let headers = message.headers();
        let key = message.key();

        // Compute new partition key (example: using a hash of the payload)
        // You can customize this logic based on your requirements
        let new_key = match self.compute_partition_key(key, headers, payload) {
            Ok(key) => key,
            Err(e) => {
                error!("Failed to compute partition key: {}", e);
                return Err(e);
            }
        };

        // Build record with new partition key, using borrowed payload
        // Headers are converted from BorrowedHeaders to OwnedHeaders only when needed
        // (FutureRecord requires OwnedHeaders due to async send semantics)
        let owned_headers = message.headers().map(|h| h.detach());

        let record = FutureRecord {
            topic: &self.config.kafka_destination_topic,
            partition: None, // producer will hash the message key to assign a destination partition
            key: Some(&new_key),
            payload,
            timestamp: message.timestamp().to_millis(),
            headers: owned_headers,
        };

        // Send to Kafka
        let future = self
            .producer
            .send_result(record)
            .map_err(|(e, _)| anyhow::anyhow!("Failed to queue message: {:?}", e))
            .context("Failed to send message to output topic")?;

        match future.await {
            Ok(Ok(_)) => Ok(()),
            Ok(Err((e, _))) => Err(anyhow::anyhow!("Failed to send: {:?}", e))
                .context("Failed to send message to output topic"),
            Err(_) => Err(anyhow::anyhow!("Send future was canceled"))
                .context("Failed to send message to output topic"),
        }
    }

    /// match the repartitioning function to the value in the deploy env config
    fn compute_partition_key(
        &self,
        source_key: Option<&[u8]>,
        headers: Option<&BorrowedHeaders>,
        payload: Option<&[u8]>,
    ) -> Result<Vec<u8>> {
        match self.config.partition_key_compute_fn.as_str() {
            "propdefs_v1" => compute_propdefs_v1_key(source_key, headers, payload),

            // TODO: map more repartitioning functions here as needed
            _ => Err(anyhow::anyhow!(
                "Unknown partition key compute function: {}",
                self.config.partition_key_compute_fn
            )),
        }
    }
}
