use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use health::{HealthHandle, HealthRegistry};
use rdkafka::consumer::Consumer;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;
use tracing::{error, info};

use crate::{
    checkpoint_manager::CheckpointManager,
    config::Config,
    deduplication_processor::{DeduplicationConfig, DeduplicationProcessor},
    kafka::{stateful_consumer::StatefulKafkaConsumer, ConsumerConfigBuilder},
    processor_pool::ProcessorPool,
    processor_rebalance_handler::ProcessorRebalanceHandler,
    store::DeduplicationStoreConfig,
    store_manager::{CleanupTaskHandle, StoreManager},
};

/// The main Kafka Deduplicator service that encapsulates all components
pub struct KafkaDeduplicatorService {
    config: Config,
    consumer: Option<StatefulKafkaConsumer>,
    store_manager: Arc<StoreManager>,
    checkpoint_manager: Option<CheckpointManager>,
    cleanup_task_handle: Option<CleanupTaskHandle>,
    processor_pool_handles: Option<Vec<tokio::task::JoinHandle<()>>>,
    processor_pool_health: Option<Arc<AtomicBool>>,
    shutdown_tx: Option<oneshot::Sender<()>>,
    liveness: HealthRegistry,
    service_health: Option<HealthHandle>,
    health_task_cancellation: CancellationToken,
    health_task_handles: Vec<tokio::task::JoinHandle<()>>,
}

impl KafkaDeduplicatorService {
    /// Create a new service from configuration
    pub fn new(config: Config, liveness: HealthRegistry) -> Result<Self> {
        // Validate configuration
        config.validate().with_context(|| format!("Configuration validation failed for service with consumer topic '{}' and group '{}'", config.kafka_consumer_topic, config.kafka_consumer_group))?;

        // Create store configuration
        let store_config = DeduplicationStoreConfig {
            path: config.store_path_buf(),
            max_capacity: config
                .parse_storage_capacity()
                .context("Failed to parse max_store_capacity")?,
        };

        // Create store manager for handling concurrent store creation
        let store_manager = Arc::new(StoreManager::new(store_config.clone()));

        // Start periodic cleanup task if max_capacity is configured
        let cleanup_task_handle = if store_config.max_capacity > 0 {
            let cleanup_interval = config.cleanup_interval();
            let handle = store_manager
                .clone()
                .start_periodic_cleanup(cleanup_interval);
            info!(
                "Started periodic cleanup task with interval: {:?} for max capacity: {} bytes",
                cleanup_interval, store_config.max_capacity
            );
            Some(handle)
        } else {
            info!("Cleanup task not started - max_capacity is unlimited (0)");
            None
        };

        // Create checkpoint manager with the store manager
        let checkpoint_manager =
            CheckpointManager::new(store_manager.clone(), config.flush_interval());
        // checkpoint_manager.start();
        info!(
            "Started checkpoint manager with flush interval: {:?}",
            config.flush_interval()
        );

        Ok(Self {
            config,
            consumer: None,
            store_manager,
            checkpoint_manager: Some(checkpoint_manager),
            cleanup_task_handle,
            processor_pool_handles: None,
            processor_pool_health: None,
            shutdown_tx: None,
            liveness,
            service_health: None,
            health_task_cancellation: CancellationToken::new(),
            health_task_handles: Vec::new(),
        })
    }

    /// Initialize the Kafka consumer and prepare for running
    pub async fn initialize(&mut self) -> Result<()> {
        if self.consumer.is_some() {
            return Err(anyhow::anyhow!("Service already initialized"));
        }

        // Create deduplication config (store config already in store_manager)
        let dedup_config = DeduplicationConfig {
            output_topic: self.config.output_topic.clone(),
            producer_config: self.config.build_producer_config(),
            store_config: DeduplicationStoreConfig {
                path: self.config.store_path_buf(),
                max_capacity: self
                    .config
                    .parse_storage_capacity()
                    .context("Failed to parse max_store_capacity")?,
            },
            producer_send_timeout: self.config.producer_send_timeout(),
            flush_interval: self.config.flush_interval(),
        };

        // Create a processor with the store manager
        let processor = DeduplicationProcessor::new(dedup_config, self.store_manager.clone())
            .with_context(|| "Failed to create deduplication processor")?;

        // Create rebalance handler with the store manager
        let rebalance_handler =
            Arc::new(ProcessorRebalanceHandler::new(self.store_manager.clone()));

        // Create consumer config using the kafka module's builder
        let consumer_config =
            ConsumerConfigBuilder::new(&self.config.kafka_hosts, &self.config.kafka_consumer_group)
                .with_tls(self.config.kafka_tls)
                .offset_reset(&self.config.kafka_consumer_offset_reset)
                .build();

        // Create shutdown channel
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
        self.shutdown_tx = Some(shutdown_tx);

        // Create processor pool with configured number of workers
        let num_workers = self.config.worker_threads;
        let (message_sender, processor_pool) = ProcessorPool::new(processor, num_workers);

        // Start the processor pool workers and get health status
        let (pool_handles, pool_health) = processor_pool.start();
        self.processor_pool_handles = Some(pool_handles);
        self.processor_pool_health = Some(pool_health.clone());

        // Register processor pool as a separate health component
        let pool_health_handle = self
            .liveness
            .register("processor_pool".to_string(), Duration::from_secs(30))
            .await;

        // Spawn task to report processor pool health
        let pool_health_reporter = pool_health.clone();
        let cancellation = self.health_task_cancellation.child_token();
        let handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(10));
            loop {
                tokio::select! {
                    _ = cancellation.cancelled() => {
                        break;
                    }
                    _ = interval.tick() => {
                        if pool_health_reporter.load(Ordering::SeqCst) {
                            pool_health_handle.report_healthy().await;
                        } else {
                            // Explicitly report unhealthy when a worker dies
                            pool_health_handle.report_status(health::ComponentStatus::Unhealthy).await;
                            error!("Processor pool is unhealthy - worker died");
                        }
                    }
                }
            }
        });
        self.health_task_handles.push(handle);

        // Create stateful Kafka consumer that sends to the processor pool
        let kafka_consumer = StatefulKafkaConsumer::from_config(
            &consumer_config,
            rebalance_handler,
            message_sender,
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

        // Register health check for the service
        self.service_health = Some(
            self.liveness
                .register("kafka_deduplicator".to_string(), Duration::from_secs(30))
                .await,
        );

        self.consumer = Some(kafka_consumer);
        Ok(())
    }

    /// Run the service (blocking until shutdown)
    pub async fn run(mut self) -> Result<()> {
        // Initialize if not already done
        if self.consumer.is_none() {
            self.initialize().await?;
        }

        let consumer = self
            .consumer
            .take()
            .ok_or_else(|| anyhow::anyhow!("Consumer not initialized"))?;

        info!("Starting Kafka Deduplicator service");

        // Start health reporting task for the main service
        if let Some(health_handle) = self.service_health.clone() {
            let cancellation = self.health_task_cancellation.child_token();
            let handle = tokio::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_secs(10));
                loop {
                    tokio::select! {
                        _ = cancellation.cancelled() => {
                            break;
                        }
                        _ = interval.tick() => {
                            health_handle.report_healthy().await;
                        }
                    }
                }
            });
            self.health_task_handles.push(handle);
        }

        // Start consumption
        let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

        // Wait for SIGTERM signal (Kubernetes graceful shutdown)
        use tokio::signal::unix::{signal, SignalKind};
        let mut sigterm = signal(SignalKind::terminate()).expect("Failed to listen for SIGTERM");

        sigterm.recv().await;
        info!("Received SIGTERM signal, shutting down gracefully...");

        // Send shutdown signal
        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
        }

        // Cancel health reporting tasks
        self.health_task_cancellation.cancel();
        for handle in self.health_task_handles.drain(..) {
            let _ = handle.await;
        }

        // Stop the checkpoint manager
        if let Some(mut checkpoint_manager) = self.checkpoint_manager.take() {
            checkpoint_manager.stop().await;
        }

        // Wait for processor pool workers to finish
        if let Some(handles) = self.processor_pool_handles.take() {
            for handle in handles {
                let _ = handle.await;
            }
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

        // Shutdown all stores cleanly
        self.store_manager.shutdown().await;

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
            self.initialize().await?;
        }

        let consumer = self
            .consumer
            .take()
            .ok_or_else(|| anyhow::anyhow!("Consumer not initialized"))?;

        info!("Starting Kafka Deduplicator service");

        // Start health reporting task for the main service
        if let Some(health_handle) = self.service_health.clone() {
            let cancellation = self.health_task_cancellation.child_token();
            let handle = tokio::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_secs(10));
                loop {
                    tokio::select! {
                        _ = cancellation.cancelled() => {
                            break;
                        }
                        _ = interval.tick() => {
                            health_handle.report_healthy().await;
                        }
                    }
                }
            });
            self.health_task_handles.push(handle);
        }

        // Start consumption
        let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

        // Wait for shutdown signal
        shutdown_signal.await;

        info!("Received shutdown signal, shutting down gracefully...");

        // Send shutdown signal
        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
        }

        // Cancel health reporting tasks
        self.health_task_cancellation.cancel();
        for handle in self.health_task_handles.drain(..) {
            let _ = handle.await;
        }

        // Stop the checkpoint manager
        if let Some(mut checkpoint_manager) = self.checkpoint_manager.take() {
            checkpoint_manager.stop().await;
        }

        // Wait for processor pool workers to finish
        if let Some(handles) = self.processor_pool_handles.take() {
            for handle in handles {
                let _ = handle.await;
            }
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

        // Shutdown all stores cleanly
        self.store_manager.shutdown().await;

        Ok(())
    }

    /// Shutdown the service gracefully
    pub async fn shutdown(&mut self) -> Result<()> {
        info!("Shutting down service...");

        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
        }

        // Stop cleanup task if running
        if let Some(handle) = self.cleanup_task_handle.take() {
            info!("Stopping cleanup task...");
            handle.stop().await;
        }

        // Give some time for graceful shutdown
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;

        Ok(())
    }
}

/// Builder for easier service configuration in tests
pub struct ServiceBuilder {
    config: Config,
    liveness: HealthRegistry,
}

impl ServiceBuilder {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            liveness: HealthRegistry::new("test_liveness"),
        }
    }

    pub fn with_output_topic(mut self, topic: String) -> Self {
        self.config.output_topic = Some(topic);
        self
    }

    pub fn with_store_path(mut self, path: String) -> Self {
        self.config.store_path = path;
        self
    }

    pub fn with_liveness(mut self, liveness: HealthRegistry) -> Self {
        self.liveness = liveness;
        self
    }

    pub fn build(self) -> Result<KafkaDeduplicatorService> {
        KafkaDeduplicatorService::new(self.config, self.liveness)
    }
}
