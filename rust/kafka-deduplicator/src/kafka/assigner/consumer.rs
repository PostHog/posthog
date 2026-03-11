use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use futures_util::StreamExt;
use kafka_assigner_proto::kafka_assigner::v1 as proto;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{
    CommitMode, Consumer, DefaultConsumerContext, MessageStream, StreamConsumer,
};
use rdkafka::error::KafkaResult;
use rdkafka::message::Message;
use rdkafka::TopicPartitionList;
use serde::Deserialize;
use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;
use tonic::Streaming;
use tracing::{error, info, warn};

use super::client::AssignerGrpcClient;
use super::handler::{proto_to_partition, AssignerCommandHandler};
use crate::checkpoint::import::CheckpointImporter;
use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_message::{Batch, BatchError, KafkaMessage};
use crate::kafka::error_handling;
use crate::kafka::metrics_consts::{
    BATCH_CONSUMER_BATCH_COLLECTION_DURATION_MS, BATCH_CONSUMER_BATCH_FILL_RATIO,
    BATCH_CONSUMER_BATCH_SIZE, BATCH_CONSUMER_KAFKA_ERROR, BATCH_CONSUMER_MESSAGES_RECEIVED,
};
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::partition_router::PartitionRouter;
use crate::kafka::types::Partition;
use crate::metrics_const::REBALANCE_CHECKPOINT_IMPORT_COUNTER;
use crate::store_manager::StoreManager;
use crate::utils::async_helpers::unwrap_blocking_task;

/// Result of a background warming (checkpoint import) task.
struct WarmResult {
    partition: Partition,
    result: Result<()>,
}

/// Kafka consumer driven by the kafka-assigner service.
///
/// Instead of using Kafka's consumer group protocol for partition assignment,
/// this consumer receives assignment commands via a gRPC stream from the
/// kafka-assigner and manually calls `assign()` on the underlying StreamConsumer.
///
/// This eliminates stop-the-world rebalances and enables warm handoffs where
/// a new consumer can download checkpoints before taking ownership.
pub struct AssignerConsumer<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    consumer: StreamConsumer,
    handler: AssignerCommandHandler<T, P>,
    command_stream: Streaming<proto::AssignmentCommand>,

    processor: Arc<RoutingProcessor<T, P>>,
    offset_tracker: Arc<OffsetTracker>,

    // For spawning warming tasks
    store_manager: Arc<StoreManager>,
    checkpoint_importer: Option<Arc<CheckpointImporter>>,

    // Config
    commit_interval: Duration,
    batch_size: usize,
    batch_timeout: Duration,

    shutdown_rx: oneshot::Receiver<()>,
}

use crate::kafka::routing_processor::RoutingProcessor;

impl<T, P> AssignerConsumer<T, P>
where
    T: for<'de> Deserialize<'de> + Send + Sync + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    /// Create a new assigner consumer, connect to the kafka-assigner, and register.
    #[allow(clippy::too_many_arguments)]
    pub async fn new(
        consumer_config: &ClientConfig,
        assigner_endpoint: &str,
        consumer_name: String,
        topic: String,
        store_manager: Arc<StoreManager>,
        checkpoint_importer: Option<Arc<CheckpointImporter>>,
        offset_tracker: Arc<OffsetTracker>,
        router: Arc<PartitionRouter<T, P>>,
        processor: Arc<RoutingProcessor<T, P>>,
        commit_interval: Duration,
        batch_size: usize,
        batch_timeout: Duration,
        shutdown_rx: oneshot::Receiver<()>,
    ) -> Result<Self> {
        // Create a plain StreamConsumer (no custom context — no rebalance callbacks)
        let consumer: StreamConsumer = consumer_config
            .create()
            .context("Failed to create Kafka consumer for assigner mode")?;

        // Connect to the kafka-assigner and register
        let mut grpc_client =
            AssignerGrpcClient::connect(assigner_endpoint, consumer_name, topic).await?;
        let command_stream = grpc_client.register().await?;

        let handler = AssignerCommandHandler::new(
            store_manager.clone(),
            offset_tracker.clone(),
            router,
            grpc_client,
        );

        Ok(Self {
            consumer,
            handler,
            command_stream,
            processor,
            offset_tracker,
            store_manager,
            checkpoint_importer,
            commit_interval,
            batch_size,
            batch_timeout,
            shutdown_rx,
        })
    }

    /// Run the main consumption loop.
    pub async fn start(mut self) -> Result<()> {
        info!("Starting assigner-driven consumption loop");

        let mut commit_interval = tokio::time::interval(self.commit_interval);
        let batch_size = self.batch_size;
        let batch_timeout = self.batch_timeout;

        // Channel for receiving warming task results
        let (warm_done_tx, mut warm_done_rx) = mpsc::channel::<WarmResult>(16);

        // Move consumer out of self so the stream borrow doesn't conflict
        // with mutable field access in command handling (same pattern as BatchConsumer)
        let consumer = self.consumer;
        let mut stream = consumer.stream();

        loop {
            tokio::select! {
                _ = &mut self.shutdown_rx => {
                    info!("Shutdown signal received, stopping assigner consumer");
                    break;
                }

                // Handle gRPC commands from the assigner
                result = self.command_stream.message() => {
                    match result {
                        Ok(Some(cmd)) => {
                            handle_command(
                                cmd,
                                &consumer,
                                &mut self.handler,
                                &self.store_manager,
                                &self.checkpoint_importer,
                                &warm_done_tx,
                            ).await?;
                        }
                        Ok(None) => {
                            warn!("Assigner command stream ended, shutting down");
                            break;
                        }
                        Err(e) => {
                            error!(error = ?e, "Assigner command stream error");
                            return Err(e).context("Assigner gRPC stream failed");
                        }
                    }
                }

                // Handle warming task completions
                Some(warm_result) = warm_done_rx.recv() => {
                    if self.handler.is_warming(&warm_result.partition) {
                        self.handler
                            .finish_warm(&warm_result.partition, warm_result.result)
                            .await?;
                    }
                }

                // Poll Kafka messages and process in batches
                batch_result = Self::consume_batch(&mut stream, batch_size, batch_timeout) => {
                    match batch_result {
                        Ok((batch, collection_duration)) => {
                            metrics::histogram!(BATCH_CONSUMER_BATCH_COLLECTION_DURATION_MS)
                                .record(collection_duration.as_millis() as f64);

                            if batch.is_empty() {
                                continue;
                            }

                            let message_count = batch.message_count();
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "success")
                                .increment(message_count as u64);
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "error")
                                .increment(batch.error_count() as u64);
                            metrics::histogram!(BATCH_CONSUMER_BATCH_SIZE)
                                .record(message_count as f64);
                            metrics::histogram!(BATCH_CONSUMER_BATCH_FILL_RATIO)
                                .record(message_count as f64 / batch_size as f64);

                            let (messages, _errors) = batch.unpack();
                            if let Err(e) = self.processor.process_batch(messages).await {
                                error!("Error processing batch: {e:#}");
                            }
                        }
                        Err(e) => {
                            return Err(e.into());
                        }
                    }
                }

                // Commit offsets periodically
                _ = commit_interval.tick() => {
                    commit_tracked_offsets(&consumer, &self.offset_tracker);
                }
            }
        }

        info!("Assigner consumer loop shut down");
        Ok(())
    }

    /// Collect a batch of messages from the Kafka stream.
    async fn consume_batch(
        stream: &mut MessageStream<'_, DefaultConsumerContext>,
        batch_size: usize,
        batch_timeout: Duration,
    ) -> KafkaResult<(Batch<T>, Duration)> {
        let start = Instant::now();
        let mut batch = Batch::new_with_size_hint(batch_size);
        let mut batch_complete = tokio::time::interval(batch_timeout);
        let mut kafka_error_count = 0;

        loop {
            tokio::select! {
                _ = batch_complete.tick() => {
                    break;
                }

                next_msg = stream.next() => {
                    match next_msg {
                        Some(Ok(borrowed_message)) => {
                            match KafkaMessage::<T>::from_borrowed_message(&borrowed_message) {
                                Ok(kafka_message) => {
                                    batch.push_message(kafka_message);
                                    kafka_error_count = 0;
                                }
                                Err(e) => {
                                    let wrapped_err = e.context("Error deserializing message");
                                    batch.push_error(BatchError::new(
                                        wrapped_err,
                                        Some(Partition::new(
                                            borrowed_message.topic().to_owned(),
                                            borrowed_message.partition(),
                                        )),
                                        Some(borrowed_message.offset()),
                                    ));
                                }
                            }
                        }
                        Some(Err(e)) => {
                            kafka_error_count += 1;
                            if let Some(ke) =
                                error_handling::handle_kafka_error(e, kafka_error_count, BATCH_CONSUMER_KAFKA_ERROR).await
                            {
                                return Err(ke);
                            }
                        }
                        None => {
                            break;
                        }
                    }

                    if batch.message_count() >= batch_size {
                        break;
                    }
                }
            }
        }

        Ok((batch, start.elapsed()))
    }
}

/// Dispatch a single gRPC command from the assigner.
///
/// Standalone function to avoid borrow conflicts (consumer is borrowed by the stream,
/// so we can't take &mut self).
async fn handle_command<T, P>(
    cmd: proto::AssignmentCommand,
    consumer: &StreamConsumer,
    handler: &mut AssignerCommandHandler<T, P>,
    store_manager: &Arc<StoreManager>,
    checkpoint_importer: &Option<Arc<CheckpointImporter>>,
    warm_done_tx: &mpsc::Sender<WarmResult>,
) -> Result<()>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    use proto::assignment_command::Command;

    let Some(command) = cmd.command else {
        warn!("Received empty AssignmentCommand");
        return Ok(());
    };

    match command {
        Command::Assignment(update) => {
            handler.handle_assignment(update, consumer).await?;
        }
        Command::Warm(warm) => {
            let proto_partition = warm
                .partition
                .as_ref()
                .expect("WarmPartition must have a partition");
            let partition = proto_to_partition(proto_partition);

            info!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                current_owner = warm.current_owner.as_str(),
                "Warming partition: spawning checkpoint import"
            );

            let cancel_token = handler.start_warm(&partition);
            spawn_warming_task(
                partition,
                cancel_token,
                store_manager.clone(),
                checkpoint_importer.clone(),
                warm_done_tx.clone(),
            );
        }
        Command::Release(release) => {
            handler.handle_release(release, consumer).await?;
        }
    }

    Ok(())
}

/// Spawn a background task that downloads a checkpoint for a partition.
fn spawn_warming_task(
    partition: Partition,
    cancel_token: CancellationToken,
    store_manager: Arc<StoreManager>,
    checkpoint_importer: Option<Arc<CheckpointImporter>>,
    done_tx: mpsc::Sender<WarmResult>,
) {
    tokio::spawn(async move {
        let result = import_checkpoint(
            &store_manager,
            checkpoint_importer.as_ref(),
            &partition,
            &cancel_token,
        )
        .await;

        let _ = done_tx.send(WarmResult { partition, result }).await;
    });
}

/// Commit processed offsets to Kafka.
///
/// In assigner mode, the rebalance tracker is never in a rebalancing state,
/// so commits are never skipped.
fn commit_tracked_offsets(consumer: &StreamConsumer, offset_tracker: &OffsetTracker) {
    let offsets = match offset_tracker.get_committable_offsets() {
        Ok(offsets) => offsets,
        Err(crate::kafka::offset_tracker::OffsetTrackerError::RebalanceInProgress) => {
            return;
        }
    };

    if offsets.is_empty() {
        return;
    }

    let mut list = TopicPartitionList::new();
    for (partition, next_offset) in &offsets {
        let _ = list.add_partition_offset(
            partition.topic(),
            partition.partition_number(),
            rdkafka::Offset::Offset(*next_offset),
        );
    }

    match consumer.commit(&list, CommitMode::Sync) {
        Ok(_) => {
            info!("Committed offsets for {} partitions", offsets.len());
            offset_tracker.mark_committed(&offsets);
        }
        Err(e) => {
            warn!("Failed to commit tracked offsets: {e:#}");
        }
    }
}

/// Download a checkpoint for a partition, creating the RocksDB store from S3.
///
/// Standalone function so it can be called from a spawned task without borrowing
/// the handler.
async fn import_checkpoint(
    store_manager: &Arc<StoreManager>,
    checkpoint_importer: Option<&Arc<CheckpointImporter>>,
    partition: &Partition,
    cancel_token: &CancellationToken,
) -> Result<()> {
    // Skip if store already exists
    if store_manager
        .get(partition.topic(), partition.partition_number())
        .is_some()
    {
        metrics::counter!(
            REBALANCE_CHECKPOINT_IMPORT_COUNTER,
            "result" => "skipped",
            "reason" => "store_exists",
            "assignment_mode" => "kafka_assigner",
        )
        .increment(1);
        info!(
            topic = partition.topic(),
            partition = partition.partition_number(),
            "Store already exists, skipping checkpoint import"
        );
        return Ok(());
    }

    let Some(importer) = checkpoint_importer else {
        metrics::counter!(
            REBALANCE_CHECKPOINT_IMPORT_COUNTER,
            "result" => "skipped",
            "reason" => "disabled",
            "assignment_mode" => "kafka_assigner",
        )
        .increment(1);
        // No importer configured, create empty store
        store_manager
            .get_or_create_for_rebalance(partition.topic(), partition.partition_number())
            .await?;
        return Ok(());
    };

    let path = match importer
        .import_checkpoint_for_topic_partition_cancellable(
            partition.topic(),
            partition.partition_number(),
            Some(cancel_token),
        )
        .await
    {
        Ok(path) => path,
        Err(e) => {
            metrics::counter!(
                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                "result" => "failed",
                "reason" => "import",
                "assignment_mode" => "kafka_assigner",
            )
            .increment(1);
            return Err(e);
        }
    };

    // Open the imported checkpoint as a RocksDB store (blocking)
    let sm = store_manager.clone();
    let topic = partition.topic().to_string();
    let partition_number = partition.partition_number();
    let import_path = path.clone();

    match unwrap_blocking_task(
        tokio::task::spawn_blocking(move || {
            sm.restore_imported_store(&topic, partition_number, &import_path)
        }),
        "restore_imported_store task panicked",
    )
    .await
    {
        Ok(_) => {
            metrics::counter!(
                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                "result" => "success",
                "assignment_mode" => "kafka_assigner",
            )
            .increment(1);
            info!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                path = %path.display(),
                "Imported and registered checkpoint store"
            );
            Ok(())
        }
        Err(e) => {
            metrics::counter!(
                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                "result" => "failed",
                "reason" => "restore",
                "assignment_mode" => "kafka_assigner",
            )
            .increment(1);
            Err(e)
        }
    }
}
