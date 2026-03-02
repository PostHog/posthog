//! Pipeline builder for creating configured pipeline consumers.
//!
//! This module provides a builder pattern for constructing pipeline-specific
//! Kafka consumers with all necessary dependencies.

use std::sync::Arc;

use anyhow::{Context, Result};
use common_kafka::kafka_producer::KafkaContext;
use common_types::{CapturedEvent, ClickHouseEvent};
use rdkafka::producer::FutureProducer;
use rdkafka::ClientConfig;
use tokio::sync::oneshot;
use tracing::info;

use crate::checkpoint::import::CheckpointImporter;
use crate::config::PipelineType;
use crate::kafka::batch_consumer::BatchConsumer;
use crate::kafka::{OffsetTracker, PartitionRouter, PartitionRouterConfig, RoutingProcessor};
use crate::pipelines::clickhouse_events::{ClickHouseEventsBatchProcessor, ClickHouseEventsConfig};
use crate::pipelines::ingestion_events::{
    DeduplicationConfig, DuplicateEventProducerWrapper, IngestionEventsBatchProcessor,
};
use crate::processor_rebalance_handler::ProcessorRebalanceHandler;
use crate::rebalance_tracker::RebalanceTracker;
use crate::store_manager::StoreManager;

/// Enum wrapper for different consumer types based on pipeline configuration.
///
/// Each variant wraps a `BatchConsumer` for the appropriate event type,
/// allowing the service to work with either pipeline through a unified interface.
pub enum PipelineConsumer {
    IngestionEvents(BatchConsumer<CapturedEvent>),
    ClickHouseEvents(BatchConsumer<ClickHouseEvent>),
}

impl PipelineConsumer {
    pub async fn start_consumption(self) -> Result<()> {
        match self {
            PipelineConsumer::IngestionEvents(consumer) => consumer.start_consumption().await,
            PipelineConsumer::ClickHouseEvents(consumer) => consumer.start_consumption().await,
        }
    }
}

/// Builder for creating pipeline consumers with all necessary dependencies.
pub struct PipelineBuilder {
    pipeline_type: PipelineType,
    store_manager: Arc<StoreManager>,
    consumer_config: ClientConfig,
    router_config: PartitionRouterConfig,
    topic: String,
    batch_size: usize,
    batch_timeout: std::time::Duration,
    commit_interval: std::time::Duration,
    seek_timeout: std::time::Duration,
    checkpoint_importer: Option<Arc<CheckpointImporter>>,
    rebalance_cleanup_parallelism: usize,

    // Fail-open mode: bypass deduplication and forward events directly
    fail_open: bool,

    // Ingestion events specific
    dedup_config: Option<DeduplicationConfig>,
    main_producer: Option<Arc<FutureProducer<KafkaContext>>>,
    duplicate_producer: Option<DuplicateEventProducerWrapper>,
}

impl PipelineBuilder {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        pipeline_type: PipelineType,
        store_manager: Arc<StoreManager>,
        consumer_config: ClientConfig,
        router_config: PartitionRouterConfig,
        topic: String,
        batch_size: usize,
        batch_timeout: std::time::Duration,
        commit_interval: std::time::Duration,
        seek_timeout: std::time::Duration,
        rebalance_cleanup_parallelism: usize,
        fail_open: bool,
    ) -> Self {
        Self {
            pipeline_type,
            store_manager,
            consumer_config,
            router_config,
            topic,
            batch_size,
            batch_timeout,
            commit_interval,
            seek_timeout,
            checkpoint_importer: None,
            rebalance_cleanup_parallelism,
            fail_open,
            dedup_config: None,
            main_producer: None,
            duplicate_producer: None,
        }
    }

    pub fn with_checkpoint_importer(mut self, importer: Option<Arc<CheckpointImporter>>) -> Self {
        self.checkpoint_importer = importer;
        self
    }

    /// Configure ingestion events pipeline specific options
    pub fn with_ingestion_config(
        mut self,
        dedup_config: DeduplicationConfig,
        main_producer: Option<Arc<FutureProducer<KafkaContext>>>,
        duplicate_producer: Option<DuplicateEventProducerWrapper>,
    ) -> Self {
        self.dedup_config = Some(dedup_config);
        self.main_producer = main_producer;
        self.duplicate_producer = duplicate_producer;
        self
    }

    /// Build the pipeline consumer
    pub fn build(self, shutdown_rx: oneshot::Receiver<()>) -> Result<PipelineConsumer> {
        let rebalance_tracker = self.store_manager.rebalance_tracker().clone();
        let offset_tracker = Arc::new(OffsetTracker::new(rebalance_tracker.clone()));

        match self.pipeline_type {
            PipelineType::IngestionEvents => {
                self.build_ingestion_events(rebalance_tracker, offset_tracker, shutdown_rx)
            }
            PipelineType::ClickhouseEvents => {
                self.build_clickhouse_events(rebalance_tracker, offset_tracker, shutdown_rx)
            }
        }
    }

    fn build_ingestion_events(
        self,
        rebalance_tracker: Arc<RebalanceTracker>,
        offset_tracker: Arc<OffsetTracker>,
        shutdown_rx: oneshot::Receiver<()>,
    ) -> Result<PipelineConsumer> {
        info!("Building ingestion_events pipeline");

        let dedup_config = self
            .dedup_config
            .context("DeduplicationConfig required for ingestion_events pipeline")?;

        let processor = Arc::new(
            IngestionEventsBatchProcessor::new(
                dedup_config,
                self.store_manager.clone(),
                self.main_producer,
                self.duplicate_producer,
            )
            .context("Failed to create ingestion events processor")?,
        );

        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            self.router_config,
        ));

        let routing_processor = Arc::new(RoutingProcessor::new(
            router.clone(),
            offset_tracker.clone(),
        ));

        let rebalance_handler = Arc::new(ProcessorRebalanceHandler::with_router(
            self.store_manager.clone(),
            rebalance_tracker,
            router,
            offset_tracker.clone(),
            self.checkpoint_importer,
            self.rebalance_cleanup_parallelism,
        ));

        let consumer = BatchConsumer::new(
            &self.consumer_config,
            rebalance_handler,
            routing_processor,
            offset_tracker,
            shutdown_rx,
            &self.topic,
            self.batch_size,
            self.batch_timeout,
            self.commit_interval,
            self.seek_timeout,
        )
        .with_context(|| format!("Failed to create consumer for topic '{}'", self.topic))?;

        Ok(PipelineConsumer::IngestionEvents(consumer))
    }

    fn build_clickhouse_events(
        self,
        rebalance_tracker: Arc<RebalanceTracker>,
        offset_tracker: Arc<OffsetTracker>,
        shutdown_rx: oneshot::Receiver<()>,
    ) -> Result<PipelineConsumer> {
        info!("Building clickhouse_events pipeline");

        let ch_config = ClickHouseEventsConfig {
            store_config: self.store_manager.config().clone(),
            fail_open: self.fail_open,
        };

        let processor = Arc::new(ClickHouseEventsBatchProcessor::new(
            ch_config,
            self.store_manager.clone(),
        ));

        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            self.router_config,
        ));

        let routing_processor = Arc::new(RoutingProcessor::new(
            router.clone(),
            offset_tracker.clone(),
        ));

        let rebalance_handler = Arc::new(ProcessorRebalanceHandler::with_router(
            self.store_manager.clone(),
            rebalance_tracker,
            router,
            offset_tracker.clone(),
            self.checkpoint_importer,
            self.rebalance_cleanup_parallelism,
        ));

        let consumer = BatchConsumer::new(
            &self.consumer_config,
            rebalance_handler,
            routing_processor,
            offset_tracker,
            shutdown_rx,
            &self.topic,
            self.batch_size,
            self.batch_timeout,
            self.commit_interval,
            self.seek_timeout,
        )
        .with_context(|| format!("Failed to create consumer for topic '{}'", self.topic))?;

        Ok(PipelineConsumer::ClickHouseEvents(consumer))
    }
}
