use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
use lifecycle::{ComponentOptions, Handle, Manager};
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
    consumer_handle: Option<Handle>,
    store_manager: Arc<StoreManager>,
    checkpoint_manager: Option<CheckpointManager>,
    checkpoint_importer: Option<Arc<CheckpointImporter>>,
    cleanup_task_handle: Option<CleanupTaskHandle>,
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

    /// Create a new service from configuration. Registers lifecycle components on the manager.
    pub async fn new(config: Config, manager: &mut Manager) -> Result<Self> {
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

        // Start periodic cleanup task if max_capacity is configured
        let cleanup_task_handle = if store_config.max_capacity > 0 {
            let cleanup_handle = manager.register(
                "cleanup-task",
                ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
            );
            let cleanup_interval = config.cleanup_interval();
            let orphan_min_staleness = config.orphan_cleanup_min_staleness();
            let handle = store_manager.clone().start_periodic_cleanup(
                cleanup_interval,
                orphan_min_staleness,
                cleanup_handle,
            );
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

        Ok(Self {
            config,
            consumer: None,
            consumer_handle: None,
            store_manager,
            checkpoint_manager: Some(checkpoint_manager),
            checkpoint_importer: importer,
            cleanup_task_handle,
        })
    }

    /// Initialize the Kafka consumer and prepare for running. Registers lifecycle components.
    pub async fn initialize(&mut self, manager: &mut Manager) -> Result<()> {
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

        // Register checkpoint manager and start it
        let checkpoint_handle = manager.register(
            "checkpoint-manager",
            ComponentOptions::new()
                .with_graceful_shutdown(self.config.checkpoint_worker_shutdown_timeout())
                .with_liveness_deadline(Duration::from_secs(30))
                .with_stall_threshold(2),
        );
        self.checkpoint_manager
            .as_mut()
            .unwrap()
            .start(checkpoint_handle);

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
        )
        .with_checkpoint_importer(self.checkpoint_importer.clone());

        // Configure pipeline-specific options for ingestion events
        if self.config.pipeline_type == PipelineType::IngestionEvents {
            let (main_producer, duplicate_producer) = self
                .create_producers_for_ingestion_pipeline(manager)
                .await?;

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
            };

            builder =
                builder.with_ingestion_config(dedup_config, main_producer, duplicate_producer);
        }

        let consumer_handle = manager.register(
            "consumer",
            ComponentOptions::new()
                .with_graceful_shutdown(self.config.shutdown_timeout())
                .with_liveness_deadline(Duration::from_secs(30))
                .with_stall_threshold(2),
        );

        let pipeline_consumer = builder.build(consumer_handle.clone())?;

        info!(
            "Initialized {:?} pipeline for topic '{}'",
            self.config.pipeline_type, self.config.kafka_consumer_topic
        );

        self.consumer_handle = Some(consumer_handle);
        self.consumer = Some(pipeline_consumer);
        Ok(())
    }

    /// Create Kafka producers for the ingestion events pipeline
    async fn create_producers_for_ingestion_pipeline(
        &self,
        manager: &mut Manager,
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

                let tag = format!("main_producer_{topic}");
                let main_producer_handle = manager.register(
                    &tag,
                    ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
                );

                let producer = create_kafka_producer(&kafka_config, main_producer_handle)
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

                let tag = format!("duplicate_producer_{topic}");
                let duplicate_producer_handle = manager.register(
                    &tag,
                    ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
                );

                let producer = create_kafka_producer(&kafka_config, duplicate_producer_handle)
                    .await
                    .with_context(|| {
                        format!(
                            "Failed to create Kafka producer for duplicate events topic '{topic}'"
                        )
                    })?;

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

    /// Spawn the consumer task with lifecycle coordination. The consumer runs until shutdown,
    /// then performs teardown (checkpoint stop, cleanup stop, store shutdown).
    pub fn spawn_consumer_task(mut self) -> Result<()> {
        let consumer = self
            .consumer
            .take()
            .ok_or_else(|| anyhow::anyhow!("Consumer not initialized"))?;

        let consumer_handle = self
            .consumer_handle
            .take()
            .ok_or_else(|| anyhow::anyhow!("Consumer handle not initialized"))?;

        let store_manager = self.store_manager.clone();
        let mut checkpoint_manager = self.checkpoint_manager.take();
        let cleanup_task_handle = self.cleanup_task_handle.take();

        info!("Starting Kafka Deduplicator service");

        tokio::spawn(async move {
            let _guard = consumer_handle.process_scope();

            match consumer.start_consumption().await {
                Ok(()) => info!("Consumer stopped normally"),
                Err(e) => error!("Consumer stopped with error: {e:#}"),
            }

            if let Some(mut cm) = checkpoint_manager.take() {
                cm.stop().await;
            }

            if let Some(handle) = cleanup_task_handle {
                info!("Stopping cleanup task...");
                handle.stop().await;
            }

            store_manager.shutdown().await;
            info!("Kafka Deduplicator service stopped");
        });

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

        assert!(!checkpoint_dir.exists());

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        assert!(checkpoint_dir.exists());
        assert!(checkpoint_dir.is_dir());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }

    #[test]
    fn test_reset_checkpoint_directory_clears_existing_files() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().join("checkpoints");
        std::fs::create_dir_all(&checkpoint_dir).unwrap();

        std::fs::write(checkpoint_dir.join("file1.txt"), "content1").unwrap();
        std::fs::write(checkpoint_dir.join("file2.txt"), "content2").unwrap();
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 2);

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }

    #[test]
    fn test_reset_checkpoint_directory_clears_nested_subdirs() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().join("checkpoints");
        std::fs::create_dir_all(&checkpoint_dir).unwrap();

        let topic_dir = checkpoint_dir.join("topic-name");
        let partition_dir = topic_dir.join("0");
        let attempt_dir = partition_dir.join("20260115_061456");
        std::fs::create_dir_all(&attempt_dir).unwrap();
        std::fs::write(attempt_dir.join("checkpoint.sst"), "sst data").unwrap();
        std::fs::write(attempt_dir.join("MANIFEST"), "manifest").unwrap();
        std::fs::write(checkpoint_dir.join("lockfile"), "").unwrap();

        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 2);

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
        assert!(!topic_dir.exists());
    }

    #[test]
    fn test_reset_checkpoint_directory_preserves_base_directory() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().to_path_buf();

        let subdir = checkpoint_dir.join("subdir");
        std::fs::create_dir_all(&subdir).unwrap();
        std::fs::write(subdir.join("file.txt"), "content").unwrap();
        std::fs::write(checkpoint_dir.join("root_file.txt"), "root").unwrap();

        let cfg = make_config(&checkpoint_dir);
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }

    #[test]
    fn test_reset_checkpoint_directory_idempotent_on_empty() {
        let temp_dir = TempDir::new().unwrap();
        let checkpoint_dir = temp_dir.path().join("checkpoints");
        std::fs::create_dir_all(&checkpoint_dir).unwrap();

        let cfg = make_config(&checkpoint_dir);

        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();
        KafkaDeduplicatorService::reset_checkpoint_directory(&cfg).unwrap();

        assert!(checkpoint_dir.exists());
        assert_eq!(std::fs::read_dir(&checkpoint_dir).unwrap().count(), 0);
    }
}
