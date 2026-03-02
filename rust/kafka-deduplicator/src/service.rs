use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;

use health::{HealthHandle, HealthRegistry};
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;
use tracing::{error, info};

use crate::config::PipelineType;
use crate::pipelines::ingestion_events::{DeduplicationConfig, DuplicateEventProducerWrapper};
use crate::pipelines::{PipelineBuilder, PipelineConsumer};
use crate::{
    checkpoint::{
        config::CheckpointConfig, export::CheckpointExporter, import::CheckpointImporter,
        s3_downloader::S3Downloader, s3_uploader::S3Uploader,
    },
    checkpoint_manager::CheckpointManager,
    config::Config,
    kafka::{PartitionRouterConfig, PartitionWorkerConfig},
    rebalance_tracker::RebalanceTracker,
    store::DeduplicationStoreConfig,
    store_manager::{CleanupTaskHandle, StoreManager},
};

/// The main Kafka Deduplicator service that encapsulates all components
pub struct KafkaDeduplicatorService {
    config: Config,
    consumer: Option<PipelineConsumer>,
    store_manager: Arc<StoreManager>,
    checkpoint_manager: Option<CheckpointManager>,
    checkpoint_importer: Option<Arc<CheckpointImporter>>,
    cleanup_task_handle: Option<CleanupTaskHandle>,
    shutdown_tx: Option<oneshot::Sender<()>>,
    liveness: HealthRegistry,
    service_health: Option<HealthHandle>,
    health_task_cancellation: CancellationToken,
    health_task_handles: Vec<tokio::task::JoinHandle<()>>,
}

impl KafkaDeduplicatorService {
    /// Reset the local checkpoint directory (clear contents, preserving the directory itself)
    fn reset_checkpoint_directory(cfg: &CheckpointConfig) -> Result<()> {
        let checkpoint_dir = &cfg.local_checkpoint_dir;
        let path = std::path::Path::new(checkpoint_dir);

        // Create directory if it doesn't exist
        if !path.exists() {
            std::fs::create_dir_all(path).with_context(|| {
                format!("Failed to create checkpoint directory: {checkpoint_dir}")
            })?;
        } else {
            // Clear contents but preserve the directory (may be a mount point)
            info!("Clearing local checkpoint directory contents: {checkpoint_dir}");
            for entry in std::fs::read_dir(path)
                .with_context(|| format!("Failed to read checkpoint directory: {checkpoint_dir}"))?
            {
                let entry = entry?;
                let entry_path = entry.path();
                if entry_path.is_dir() {
                    std::fs::remove_dir_all(&entry_path).with_context(|| {
                        format!(
                            "Failed to remove checkpoint subdirectory: {}",
                            entry_path.display()
                        )
                    })?;
                } else {
                    std::fs::remove_file(&entry_path).with_context(|| {
                        format!("Failed to remove checkpoint file: {}", entry_path.display())
                    })?;
                }
            }
        }

        info!("Local checkpoint directory ready: {checkpoint_dir}");
        Ok(())
    }

    /// Create a new service from configuration
    pub async fn new(config: Config, liveness: HealthRegistry) -> Result<Self> {
        // Validate configuration
        config.validate().with_context(|| format!("Configuration validation failed for service with consumer topic '{}' and group '{}'", config.kafka_consumer_topic, config.kafka_consumer_group))?;

        // Create store configuration
        let store_config = DeduplicationStoreConfig {
            path: config.store_path_buf(),
            max_capacity: config
                .parse_storage_capacity()
                .context("Failed to parse max_store_capacity")?,
        };

        // Create rebalance coordinator first (other components depend on it)
        let rebalance_tracker = Arc::new(RebalanceTracker::new());

        // Create store manager for handling concurrent store creation
        let store_manager = Arc::new(StoreManager::new(
            store_config.clone(),
            rebalance_tracker.clone(),
        ));

        // In fail-open mode, skip store cleanup and checkpoint infrastructure
        let (cleanup_task_handle, checkpoint_manager, importer) = if config.fail_open {
            info!("Fail-open mode enabled — skipping cleanup task, checkpoint export/import");
            let checkpoint_config = CheckpointConfig::default();
            let checkpoint_manager =
                CheckpointManager::new(checkpoint_config, store_manager.clone(), None);
            (None, checkpoint_manager, None)
        } else {
            Self::create_store_infrastructure(&config, &store_config, &store_manager).await?
        };

        Ok(Self {
            config,
            consumer: None,
            store_manager,
            checkpoint_manager: Some(checkpoint_manager),
            checkpoint_importer: importer,
            cleanup_task_handle,
            shutdown_tx: None,
            liveness,
            service_health: None,
            health_task_cancellation: CancellationToken::new(),
            health_task_handles: Vec::new(),
        })
    }

    /// Create cleanup task, checkpoint exporter, and checkpoint importer.
    /// Skipped entirely when fail-open mode is active.
    async fn create_store_infrastructure(
        config: &Config,
        store_config: &DeduplicationStoreConfig,
        store_manager: &Arc<StoreManager>,
    ) -> Result<(
        Option<CleanupTaskHandle>,
        CheckpointManager,
        Option<Arc<CheckpointImporter>>,
    )> {
        // Start periodic cleanup task if max_capacity is configured
        let cleanup_task_handle = if store_config.max_capacity > 0 {
            let cleanup_interval = config.cleanup_interval();
            let orphan_min_staleness = config.orphan_cleanup_min_staleness();
            let handle = store_manager
                .clone()
                .start_periodic_cleanup(cleanup_interval, orphan_min_staleness);
            info!(
                "Started periodic cleanup task with interval: {:?} for max capacity: {} bytes",
                cleanup_interval, store_config.max_capacity
            );
            Some(handle)
        } else {
            info!("Cleanup task not started - max_capacity is unlimited (0)");
            None
        };

        // Create checkpoint manager and inject an exporter to enable uploads
        let checkpoint_config = CheckpointConfig {
            checkpoint_interval: config.checkpoint_interval(),
            checkpoint_full_upload_interval: config.checkpoint_full_upload_interval,
            local_checkpoint_dir: config.local_checkpoint_dir.clone(),
            s3_bucket: config.s3_bucket.clone().unwrap_or_default(),
            s3_key_prefix: config.s3_key_prefix.clone(),
            aws_region: config.aws_region.clone(),
            s3_endpoint: config.s3_endpoint.clone(),
            s3_access_key_id: config.s3_access_key_id.clone(),
            s3_secret_access_key: config.s3_secret_access_key.clone(),
            s3_force_path_style: config.s3_force_path_style,
            max_concurrent_checkpoints: config.max_concurrent_checkpoints,
            checkpoint_gate_interval: config.checkpoint_gate_interval(),
            checkpoint_worker_shutdown_timeout: config.checkpoint_worker_shutdown_timeout(),
            checkpoint_import_window_hours: config.checkpoint_import_window_hours,
            s3_operation_timeout: config.s3_operation_timeout(),
            s3_attempt_timeout: config.s3_attempt_timeout(),
            s3_max_retries: config.s3_max_retries,
            checkpoint_import_attempt_depth: config.checkpoint_import_attempt_depth,
            max_concurrent_checkpoint_file_downloads: config
                .max_concurrent_checkpoint_file_downloads,
            max_concurrent_checkpoint_file_uploads: config.max_concurrent_checkpoint_file_uploads,
            checkpoint_partition_import_timeout: config.checkpoint_partition_import_timeout(),
        };

        // Reset local checkpoint directory on startup (it's temporary storage)
        Self::reset_checkpoint_directory(&checkpoint_config)?;

        // create exporter conditionally if S3 config is populated
        let exporter = if config.checkpoint_export_enabled() {
            let uploader = match S3Uploader::new(checkpoint_config.clone()).await {
                Ok(uploader) => Box::new(uploader),
                Err(e) => {
                    error!(
                        error = ?e,
                        bucket = %config.s3_bucket.as_deref().unwrap_or(""),
                        region = %config.aws_region.as_deref().unwrap_or(""),
                        "Failed to initialize S3 client for checkpoint uploads"
                    );
                    return Err(e.context("S3 uploader: client initialization failed"));
                }
            };
            Some(Arc::new(CheckpointExporter::new(uploader)))
        } else {
            None
        };

        // if checkpoint import is enabled, create and configure the importer
        let importer = if config.checkpoint_import_enabled() {
            let downloader = match S3Downloader::new(&checkpoint_config).await {
                Ok(downloader) => Box::new(downloader),
                Err(e) => {
                    error!(
                        error = ?e,
                        bucket = %config.s3_bucket.as_deref().unwrap_or(""),
                        region = %config.aws_region.as_deref().unwrap_or(""),
                        "Failed to initialize S3 client for checkpoint downloads"
                    );
                    return Err(e.context("S3 downloader: client initialization failed"));
                }
            };
            Some(Arc::new(CheckpointImporter::new(
                downloader,
                store_config.path.clone(),
                config.checkpoint_import_attempt_depth,
                config.checkpoint_partition_import_timeout(),
            )))
        } else {
            None
        };

        let checkpoint_manager =
            CheckpointManager::new(checkpoint_config, store_manager.clone(), exporter);

        Ok((cleanup_task_handle, checkpoint_manager, importer))
    }

    /// Initialize the Kafka consumer and prepare for running
    pub async fn initialize(&mut self) -> Result<()> {
        if self.consumer.is_some() {
            return Err(anyhow::anyhow!("Service already initialized"));
        }

        let consumer_config = self.config.build_batch_consumer_config();

        // Create partition router for parallel processing across partitions
        let router_config = PartitionRouterConfig {
            worker_config: PartitionWorkerConfig {
                channel_buffer_size: self.config.partition_worker_channel_buffer_size,
            },
        };

        // Create shutdown channel
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
        self.shutdown_tx = Some(shutdown_tx);

        // start checkpoint manager and async work loop threads, register health monitor
        let checkpoint_health_reporter = self.checkpoint_manager.as_mut().unwrap().start();

        // if health reporter is Some, this is the first time initializing
        // the checkpoint manager, and we should start the health monitor thread
        if checkpoint_health_reporter.is_some() {
            let checkpoint_health_handle = self
                .liveness
                .register("checkpoint_manager".to_string(), Duration::from_secs(30))
                .await;
            let cancellation = self.health_task_cancellation.child_token();
            let handle = tokio::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_secs(10));
                loop {
                    tokio::select! {
                        _ = cancellation.cancelled() => {
                            break;
                        }
                        _ = interval.tick() => {
                            if checkpoint_health_reporter.as_ref().unwrap().load(Ordering::SeqCst) {
                                checkpoint_health_handle.report_healthy().await;
                            } else {
                                // Explicitly report unhealthy when a worker dies
                                checkpoint_health_handle.report_status(health::ComponentStatus::Unhealthy).await;
                                error!("Checkpoint manager is unhealthy - checkpoint and/or cleanup loops died");
                            }
                        }
                    }
                }
            });
            self.health_task_handles.push(handle);
        }

        info!(
            "Started checkpoint manager (export enabled = {:?}, checkpoint interval = {:?})",
            self.checkpoint_manager.as_ref().unwrap().export_enabled(),
            self.config.checkpoint_interval(),
        );

        // Build pipeline consumer using the builder
        let mut builder = PipelineBuilder::new(
            self.config.pipeline_type,
            self.store_manager.clone(),
            consumer_config,
            router_config,
            self.config.kafka_consumer_topic.clone(),
            self.config.kafka_consumer_batch_size,
            self.config.kafka_consumer_batch_timeout(),
            self.config.commit_interval(),
            self.config.kafka_consumer_seek_timeout(),
            self.config.rebalance_cleanup_parallelism,
            self.config.fail_open,
        )
        .with_checkpoint_importer(self.checkpoint_importer.clone());

        // Configure pipeline-specific options for ingestion events
        if self.config.pipeline_type == PipelineType::IngestionEvents {
            let (main_producer, duplicate_producer) =
                self.create_producers_for_ingestion_pipeline().await?;

            // Normalize empty strings to None for optional topic configs
            let output_topic = self
                .config
                .output_topic
                .as_ref()
                .filter(|s| !s.is_empty())
                .cloned();
            let duplicate_events_topic = self
                .config
                .duplicate_events_topic
                .as_ref()
                .filter(|s| !s.is_empty())
                .cloned();

            // Create deduplication config (store config already in store_manager)
            let dedup_config = DeduplicationConfig {
                output_topic,
                duplicate_events_topic,
                producer_config: self.config.build_producer_config(),
                store_config: self.store_manager.config().clone(),
                producer_send_timeout: self.config.producer_send_timeout(),
                flush_interval: self.config.flush_interval(),
                fail_open: self.config.fail_open,
            };

            builder =
                builder.with_ingestion_config(dedup_config, main_producer, duplicate_producer);
        }

        let pipeline_consumer = builder.build(shutdown_rx)?;

        info!(
            "Initialized {:?} pipeline for topic '{}'",
            self.config.pipeline_type, self.config.kafka_consumer_topic
        );

        // Register health check for the service
        self.service_health = Some(
            self.liveness
                .register("kafka_deduplicator".to_string(), Duration::from_secs(30))
                .await,
        );

        self.consumer = Some(pipeline_consumer);
        Ok(())
    }

    /// Create Kafka producers for the ingestion events pipeline
    async fn create_producers_for_ingestion_pipeline(
        &self,
    ) -> Result<(
        Option<Arc<rdkafka::producer::FutureProducer<common_kafka::kafka_producer::KafkaContext>>>,
        Option<DuplicateEventProducerWrapper>,
    )> {
        // Create KafkaConfig from our Config (used for both producers)
        let kafka_config = KafkaConfig {
            kafka_hosts: self.config.kafka_hosts.clone(),
            kafka_producer_linger_ms: self.config.kafka_producer_linger_ms,
            kafka_producer_queue_mib: self.config.kafka_producer_queue_mib,
            kafka_producer_queue_messages: self.config.kafka_producer_queue_messages,
            kafka_message_timeout_ms: self.config.kafka_message_timeout_ms,
            kafka_compression_codec: self.config.kafka_compression_codec.clone(),
            kafka_tls: self.config.kafka_tls,
            kafka_client_rack: String::new(),
            kafka_client_id: String::new(),
        };

        // Normalize empty strings to None for optional topic configs
        let output_topic = self
            .config
            .output_topic
            .as_ref()
            .filter(|s| !s.is_empty())
            .cloned();
        let duplicate_events_topic = self
            .config
            .duplicate_events_topic
            .as_ref()
            .filter(|s| !s.is_empty())
            .cloned();

        // Create main producer for output topic if configured
        let main_producer = match &output_topic {
            Some(topic) => {
                info!("Creating Kafka producer for output topic: {}", topic);

                // Create a health handle for the main producer
                let main_producer_health = self
                    .liveness
                    .register(format!("main_producer_{topic}"), Duration::from_secs(30))
                    .await;

                // Create the producer using common module's function
                let producer = create_kafka_producer(&kafka_config, main_producer_health)
                    .await
                    .with_context(|| {
                        format!("Failed to create Kafka producer for output topic '{topic}'")
                    })?;

                Some(Arc::new(producer))
            }
            None => {
                info!("Output topic not configured, skipping main producer creation");
                None
            }
        };

        // Create duplicate events producer if configured
        let duplicate_producer = match &duplicate_events_topic {
            Some(topic) => {
                info!(
                    "Creating Kafka producer for duplicate events topic: {}",
                    topic
                );

                // Create a health handle for the duplicate producer
                let duplicate_producer_health = self
                    .liveness
                    .register(
                        format!("duplicate_producer_{topic}"),
                        Duration::from_secs(30),
                    )
                    .await;

                // Create the producer using common module's function
                let producer = create_kafka_producer(&kafka_config, duplicate_producer_health)
                    .await
                    .with_context(|| {
                        format!(
                            "Failed to create Kafka producer for duplicate events topic '{topic}'"
                        )
                    })?;

                // Wrap in DuplicateEventProducerWrapper
                Some(DuplicateEventProducerWrapper::new(
                    topic.clone(),
                    Arc::new(producer),
                )?)
            }
            None => {
                info!(
                    "Duplicate events topic not configured, skipping duplicate producer creation"
                );
                None
            }
        };

        Ok((main_producer, duplicate_producer))
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::checkpoint::config::CheckpointConfig;
    use tempfile::TempDir;

    fn make_config(dir: &std::path::Path) -> CheckpointConfig {
        CheckpointConfig {
            local_checkpoint_dir: dir.to_string_lossy().to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_reset_checkpoint_directory_creates_if_not_exists() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().join("checkpoints");

        // Directory doesn't exist yet
        assert!(!checkpoint_dir.exists());

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        // Directory now exists and is empty
        assert!(checkpoint_dir.exists());
        assert!(checkpoint_dir.is_dir());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }

    #[test]
    fn test_reset_checkpoint_directory_clears_existing_files() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().join("checkpoints");
        std::fs::create_dir_all(&checkpoint_dir).unwrap();

        // Create some files
        std::fs::write(checkpoint_dir.join("file1.txt"), "content1").unwrap();
        std::fs::write(checkpoint_dir.join("file2.txt"), "content2").unwrap();
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 2);

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        // Directory still exists but is now empty
        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }

    #[test]
    fn test_reset_checkpoint_directory_clears_nested_subdirs() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().join("checkpoints");
        std::fs::create_dir_all(&checkpoint_dir).unwrap();

        // Create nested structure like real checkpoint dirs
        let topic_dir = checkpoint_dir.join("topic-name");
        let partition_dir = topic_dir.join("0");
        let attempt_dir = partition_dir.join("20260115_061456");
        std::fs::create_dir_all(&attempt_dir).unwrap();
        std::fs::write(attempt_dir.join("checkpoint.sst"), "sst data").unwrap();
        std::fs::write(attempt_dir.join("MANIFEST"), "manifest").unwrap();

        // Also a file at top level
        std::fs::write(checkpoint_dir.join("lockfile"), "").unwrap();

        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 2);

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        // Directory still exists but all contents cleared
        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
        assert!(!topic_dir.exists());
    }

    #[test]
    fn test_reset_checkpoint_directory_preserves_base_directory() {
        let temp_dir = TempDir::new().unwrap();
        // Use the temp_dir itself as the checkpoint dir (simulates mount point)
        let checkpoint_dir = temp_dir.path().to_path_buf();

        // Create some content
        let subdir = checkpoint_dir.join("subdir");
        std::fs::create_dir_all(&subdir).unwrap();
        std::fs::write(subdir.join("file.txt"), "content").unwrap();
        std::fs::write(checkpoint_dir.join("root_file.txt"), "root").unwrap();

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        // Base directory preserved, contents cleared
        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }

    #[test]
    fn test_reset_checkpoint_directory_idempotent_on_empty() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().join("checkpoints");
        std::fs::create_dir_all(&checkpoint_dir).unwrap();

        let cfg = make_config(&checkpoint_dir);

        // Call multiple times on empty directory
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }
}
