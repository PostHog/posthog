use std::sync::Arc;

use anyhow::{Context, Result};
use rdkafka::consumer::Consumer;
use tokio::sync::oneshot;
use tracing::{error, info};

use crate::{
    config::Config,
    deduplication_processor::{DeduplicationConfig, DeduplicationProcessor},
    kafka::{stateful_consumer::StatefulKafkaConsumer, ConsumerConfigBuilder},
    processor_rebalance_handler::ProcessorRebalanceHandler,
    rocksdb::deduplication_store::DeduplicationStoreConfig,
};

/// The main Kafka Deduplicator service that encapsulates all components
pub struct KafkaDeduplicatorService {
    config: Config,
    consumer: Option<StatefulKafkaConsumer<DeduplicationProcessor>>,
    processor: Arc<DeduplicationProcessor>,
    shutdown_tx: Option<oneshot::Sender<()>>,
}

impl KafkaDeduplicatorService {
    /// Create a new service from configuration
    pub fn new(config: Config) -> Result<Self> {
        // Validate configuration
        config.validate().with_context(|| format!("Configuration validation failed for service with consumer topic '{}' and group '{}'", config.kafka_consumer_topic, config.kafka_consumer_group))?;

        // Create deduplication store config
        let store_config = DeduplicationStoreConfig {
            path: config.store_path_buf(),
            max_capacity: config
                .parse_storage_capacity()
                .context("Failed to parse max_store_capacity")?,
        };

        // Create deduplication processor
        let dedup_config = DeduplicationConfig {
            output_topic: config.output_topic.clone(),
            producer_config: config.build_producer_config(),
            store_config,
            producer_send_timeout: config.producer_send_timeout(),
        };

        let processor = Arc::new(
            DeduplicationProcessor::new(dedup_config)
                .with_context(|| format!("Failed to create deduplication processor with output topic {:?} and store path '{}'", config.output_topic, config.store_path))?,
        );

        Ok(Self {
            config,
            consumer: None,
            processor,
            shutdown_tx: None,
        })
    }

    /// Create a service with a custom processor (useful for testing)
    pub fn with_processor(config: Config, processor: Arc<DeduplicationProcessor>) -> Result<Self> {
        config.validate().with_context(|| {
            "Configuration validation failed for service with custom processor".to_string()
        })?;

        Ok(Self {
            config,
            consumer: None,
            processor,
            shutdown_tx: None,
        })
    }

    /// Initialize the Kafka consumer and prepare for running
    pub fn initialize(&mut self) -> Result<()> {
        if self.consumer.is_some() {
            return Err(anyhow::anyhow!("Service already initialized"));
        }

        // Create rebalance handler
        let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(self.processor.clone()));

        // Create consumer config using the kafka module's builder
        let consumer_config =
            ConsumerConfigBuilder::new(&self.config.kafka_hosts, &self.config.kafka_consumer_group)
                .with_tls(self.config.kafka_tls)
                .offset_reset(&self.config.kafka_consumer_offset_reset)
                .build();

        // Create shutdown channel
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
        self.shutdown_tx = Some(shutdown_tx);

        // Create stateful Kafka consumer with our processor
        let kafka_consumer = StatefulKafkaConsumer::from_config(
            &consumer_config,
            rebalance_handler,
            self.processor.clone(),
            self.config.max_in_flight_messages,
            self.config.commit_interval(),
            shutdown_rx,
        )
        .with_context(|| {
            format!(
                "Failed to create Kafka consumer for topic '{}' with group '{}'",
                self.config.kafka_consumer_topic, self.config.kafka_consumer_group
            )
        })?;

        // Subscribe to input topic
        kafka_consumer
            .inner_consumer()
            .subscribe(&[&self.config.kafka_consumer_topic])
            .with_context(|| {
                format!(
                    "Failed to subscribe to input topic '{}'",
                    self.config.kafka_consumer_topic
                )
            })?;

        info!(
            "Initialized consumer for topic '{}', publishing to '{:?}'",
            self.config.kafka_consumer_topic, self.config.output_topic
        );

        self.consumer = Some(kafka_consumer);
        Ok(())
    }

    /// Run the service (blocking until shutdown)
    pub async fn run(mut self) -> Result<()> {
        // Initialize if not already done
        if self.consumer.is_none() {
            self.initialize()?;
        }

        let consumer = self
            .consumer
            .take()
            .ok_or_else(|| anyhow::anyhow!("Consumer not initialized"))?;

        info!("Starting Kafka Deduplicator service");

        // Start consumption
        let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

        // Wait for shutdown signal
        tokio::signal::ctrl_c()
            .await
            .expect("Failed to listen for ctrl+c signal");

        info!("Received shutdown signal, shutting down gracefully...");

        // Send shutdown signal
        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
        }

        // Wait for consumer to finish with timeout
        match tokio::time::timeout(self.config.shutdown_timeout(), consumer_handle).await {
            Ok(Ok(Ok(_))) => info!("Consumer stopped normally"),
            Ok(Ok(Err(e))) => error!("Consumer stopped with error: {e:#}"),
            Ok(Err(e)) => error!("Consumer task panicked: {e:#}"),
            Err(_) => error!(
                "Consumer shutdown timed out after {:?}",
                self.config.shutdown_timeout()
            ),
        }

        info!("Kafka Deduplicator service stopped");
        Ok(())
    }

    /// Run the service with a custom shutdown signal (useful for testing)
    pub async fn run_with_shutdown(
        mut self,
        shutdown_signal: impl std::future::Future<Output = ()>,
    ) -> Result<()> {
        // Initialize if not already done
        if self.consumer.is_none() {
            self.initialize()?;
        }

        let consumer = self
            .consumer
            .take()
            .ok_or_else(|| anyhow::anyhow!("Consumer not initialized"))?;

        info!("Starting Kafka Deduplicator service");

        // Start consumption
        let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

        // Wait for shutdown signal
        shutdown_signal.await;

        info!("Received shutdown signal, shutting down gracefully...");

        // Send shutdown signal
        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
        }

        // Wait for consumer to finish with timeout
        match tokio::time::timeout(self.config.shutdown_timeout(), consumer_handle).await {
            Ok(Ok(Ok(_))) => info!("Consumer stopped normally"),
            Ok(Ok(Err(e))) => error!("Consumer stopped with error: {e:#}"),
            Ok(Err(e)) => error!("Consumer task panicked: {e:#}"),
            Err(_) => error!(
                "Consumer shutdown timed out after {:?}",
                self.config.shutdown_timeout()
            ),
        }

        Ok(())
    }

    /// Shutdown the service gracefully
    pub async fn shutdown(&mut self) -> Result<()> {
        info!("Shutting down service...");

        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
        }

        // Give some time for graceful shutdown
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;

        Ok(())
    }

    /// Get the underlying processor (useful for testing)
    pub fn processor(&self) -> &Arc<DeduplicationProcessor> {
        &self.processor
    }
}

/// Builder for easier service configuration in tests
pub struct ServiceBuilder {
    config: Config,
    processor: Option<Arc<DeduplicationProcessor>>,
}

impl ServiceBuilder {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            processor: None,
        }
    }

    pub fn with_processor(mut self, processor: Arc<DeduplicationProcessor>) -> Self {
        self.processor = Some(processor);
        self
    }

    pub fn with_output_topic(mut self, topic: String) -> Self {
        self.config.output_topic = Some(topic);
        self
    }

    pub fn with_store_path(mut self, path: String) -> Self {
        self.config.store_path = path;
        self
    }

    pub fn build(self) -> Result<KafkaDeduplicatorService> {
        match self.processor {
            Some(processor) => KafkaDeduplicatorService::with_processor(self.config, processor),
            None => KafkaDeduplicatorService::new(self.config),
        }
    }
}
