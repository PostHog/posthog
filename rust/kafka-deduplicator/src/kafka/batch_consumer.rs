use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::runtime::Handle;
use tokio::sync::mpsc;

use crate::kafka::batch_message::{Batch, BatchError, KafkaMessage};
use crate::kafka::metrics_consts::{BATCH_CONSUMER_KAFKA_ERRORS, BATCH_CONSUMER_MESSAGES_RECEIVED};
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::stateful_context::RebalanceEvent; // TODO(eli): move this to rebalance_handler.rs
use crate::kafka::types::Partition;

use anyhow::anyhow;
use anyhow::{Context, Result};
use futures_util::StreamExt;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, MessageStream, Rebalance, StreamConsumer,
};
use rdkafka::error::KafkaResult;
use rdkafka::message::Message;
use rdkafka::{ClientContext, TopicPartitionList};
use serde::Deserialize;
use tokio::sync::mpsc::UnboundedSender;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

pub struct BatchConsumerContext {
    rebalance_handler: Arc<dyn RebalanceHandler>,
    /// Handle to the async runtime for executing async callbacks from sync context
    rt_handle: Handle,
    /// Channel to send rebalance events to async worker
    rebalance_tx: mpsc::UnboundedSender<RebalanceEvent>,
}
impl BatchConsumerContext {
    pub fn new(rebalance_handler: Arc<dyn RebalanceHandler>) -> Self {
        // Create channel for rebalance events
        let (tx, rx) = mpsc::unbounded_channel();

        // Start the async rebalance worker
        let worker_handler = rebalance_handler.clone();
        Handle::current().spawn(async move {
            Self::rebalance_worker(rx, worker_handler).await;
        });

        Self {
            rebalance_handler,
            rt_handle: Handle::current(),
            rebalance_tx: tx,
        }
    }

    /// Async worker that processes rebalance events
    async fn rebalance_worker(
        mut rx: mpsc::UnboundedReceiver<RebalanceEvent>,
        handler: Arc<dyn RebalanceHandler>,
    ) {
        info!("Starting rebalance worker");

        while let Some(event) = rx.recv().await {
            match event {
                RebalanceEvent::Revoke(partitions) => {
                    info!(
                        "Rebalance worker: processing revocation for {} partitions",
                        partitions.len()
                    );

                    info!(
                        "Rebalance worker: all in-flight messages completed for {} partitions",
                        partitions.len()
                    );

                    // TODO(eli): what replaces in-flight tracker here?

                    // Create TopicPartitionList for handler
                    let mut tpl = TopicPartitionList::new();
                    for partition in &partitions {
                        tpl.add_partition(partition.topic(), partition.partition_number());
                    }

                    // Call user's revocation handler
                    if let Err(e) = handler.on_partitions_revoked(&tpl).await {
                        error!("Partition revocation handler failed: {}", e);
                    }
                }
                RebalanceEvent::Assign(partitions) => {
                    info!(
                        "Rebalance worker: processing assignment for {} partitions",
                        partitions.len()
                    );

                    // TODO(eli): what replaces in-flight tracker here?

                    // Create TopicPartitionList for handler
                    let mut tpl = TopicPartitionList::new();
                    for partition in &partitions {
                        tpl.add_partition(partition.topic(), partition.partition_number());
                    }

                    // Call user's assignment handler
                    if let Err(e) = handler.on_partitions_assigned(&tpl).await {
                        error!("Partition assignment handler failed: {}", e);
                    }
                }
            }
        }

        info!("Rebalance worker shutting down");
    }
}

impl ClientContext for BatchConsumerContext {}

impl ConsumerContext for BatchConsumerContext {
    fn pre_rebalance(&self, _base_consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        info!("Pre-rebalance event: {:?}", rebalance);

        // Call user's pre-rebalance handler asynchronously
        let handler = self.rebalance_handler.clone();
        self.rt_handle.spawn(async move {
            if let Err(e) = handler.on_pre_rebalance().await {
                error!("Pre-rebalance handler failed: {}", e);
            }
        });

        // Handle partition revocation if applicable
        match rebalance {
            Rebalance::Revoke(partitions) => {
                info!("Revoking {} partitions", partitions.count());

                let partitions: Vec<Partition> = partitions
                    .elements()
                    .into_iter()
                    .map(Partition::from)
                    .collect();

                // TODO(eli): rethink fencing operation without in-flight tracker

                // Send revocation event to async worker
                if let Err(e) = self.rebalance_tx.send(RebalanceEvent::Revoke(partitions)) {
                    error!("Failed to send revoke event to rebalance worker: {}", e);
                }
            }
            Rebalance::Assign(partitions) => {
                info!(
                    "Pre-rebalance assign event for {} partitions",
                    partitions.count()
                );
            }
            Rebalance::Error(e) => {
                error!("Rebalance error: {}", e);
            }
        }
    }

    fn post_rebalance(&self, _base_consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        info!("Post-rebalance event: {:?}", rebalance);

        // Handle partition assignment if applicable
        match rebalance {
            Rebalance::Assign(partitions) => {
                info!("Assigned {} partitions", partitions.count());

                // Extract partition info
                let partitions: Vec<Partition> = partitions
                    .elements()
                    .into_iter()
                    .map(Partition::from)
                    .collect();

                info!("📋 Total partitions assigned: {:?}", partitions);

                // Send assignment event to async worker
                if let Err(e) = self.rebalance_tx.send(RebalanceEvent::Assign(partitions)) {
                    error!("Failed to send assign event to rebalance worker: {}", e);
                }
            }
            Rebalance::Revoke(_) => {
                info!("Post-rebalance revoke event");
            }
            Rebalance::Error(e) => {
                error!("Post-rebalance error: {}", e);
            }
        }

        // Call user's post-rebalance handler
        let handler = self.rebalance_handler.clone();
        self.rt_handle.spawn(async move {
            if let Err(e) = handler.on_post_rebalance().await {
                error!("Post-rebalance handler failed: {}", e);
            }
        });
    }

    fn commit_callback(
        &self,
        result: rdkafka::error::KafkaResult<()>,
        offsets: &TopicPartitionList,
    ) {
        match result {
            Ok(_) => {
                info!(
                    "Successfully committed offsets for {} partitions",
                    offsets.count()
                );
            }
            Err(e) => {
                warn!("Failed to commit offsets: {}", e);
            }
        }
    }
}

pub struct BatchConsumer<T> {
    consumer: StreamConsumer<BatchConsumerContext>,

    // group offset commit interval
    commit_interval: Duration,

    // batch configs - how big should batches get
    // and how long to wait before we publish one
    // for downstream processing
    batch_size: usize,
    batch_timeout: Duration,

    // where we send batches after consuming them
    sender: UnboundedSender<Batch<T>>,

    // shutdown signal from parent process which
    // we assume will be wrapping start_consumption
    // in a spawned thread
    shutdown_token: CancellationToken,
}

impl<T> BatchConsumer<T>
where
    T: for<'de> Deserialize<'de>,
{
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        config: &ClientConfig,
        rebalance_handler: Arc<dyn RebalanceHandler>,
        sender: UnboundedSender<Batch<T>>,
        shutdown_token: CancellationToken,
        topic: &str,
        batch_size: usize,
        batch_timeout: Duration,
        commit_interval: Duration,
    ) -> Result<Self> {
        let consumer_ctx = BatchConsumerContext::new(rebalance_handler);
        let consumer: StreamConsumer<BatchConsumerContext> = config
            .create_with_context(consumer_ctx)
            .context("Failed to create Kafka consumer")?;

        let err_msg = format!("Failed to subscribe to topic: {topic}");
        consumer.subscribe(&[topic]).context(err_msg)?;

        Ok(Self {
            consumer,
            commit_interval,
            batch_size,
            batch_timeout,
            sender,
            shutdown_token,
        })
    }

    /// Start consuming messages in a loop with graceful shutdown support
    pub async fn start_consumption(self) -> Result<()> {
        info!("Starting batch Kafka message consumption...");

        let batch_timeout = self.batch_timeout;
        let batch_size = self.batch_size;
        let mut commit_interval = tokio::time::interval(self.commit_interval);

        // consume the clients and channels needed to operate the loop
        let shutdown_token = self.shutdown_token.clone();
        let sender = self.sender;
        let consumer = self.consumer;
        let mut stream = consumer.stream();

        loop {
            tokio::select! {
                // Check for shutdown signal
                _ = shutdown_token.cancelled() => {
                    info!("Shutdown signal received, starting graceful shutdown");
                    break;
                }

                // Poll for messages
                batch_result = Self::consume_batch(&mut stream, shutdown_token.clone(), batch_size, batch_timeout) => {
                    match batch_result {
                        Ok(batch) => {
                            // track latest offsets with rdkafka consumer
                            Self::store_offsets(&consumer, &batch);
                            // if there are no errors or messages to report, skip sending
                            if batch.is_empty() {
                                continue;
                            }
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "success")
                            .increment(batch.message_count() as u64);
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "error")
                            .increment(batch.error_count() as u64);

                            if let Err(e) = sender.send(batch) {
                                // TODO: stat this
                                error!("Error sending Batch for processing: {e}");
                            }
                        }

                        Err(e) => {
                            metrics::counter!(BATCH_CONSUMER_KAFKA_ERRORS).increment(1);
                            error!("Error consuming Batch from stream: {e}");
                        }
                    }
                }

                // Commit offsets periodically that we store after each batch
                _ = commit_interval.tick() => {
                    let _ = Self::commit_offsets(&consumer);
                }
            }
        }
        info!("Batch consumer loop shutting down...");

        // Drop the sender to signal no more messages
        drop(sender);
        info!("Graceful shutdown completed");

        Ok(())
    }

    // NOT FOR PROD - handy for integration smoke tests
    pub fn inner_consumer(&self) -> &StreamConsumer<BatchConsumerContext> {
        &self.consumer
    }

    /// best-effort attempt to store latest offsets seen in the supplied Batch
    fn store_offsets(consumer: &StreamConsumer<BatchConsumerContext>, batch: &Batch<T>) {
        let mut offsets = HashMap::<Partition, i64>::new();
        for kmsg in batch.get_messages() {
            let partition = kmsg.get_topic_partition();

            if let Some(current) = offsets.get(&partition) {
                if kmsg.get_offset() + 1 > *current {
                    offsets.insert(partition, kmsg.get_offset() + 1);
                }
            } else {
                offsets.insert(partition, kmsg.get_offset() + 1);
            }
        }

        let mut list = TopicPartitionList::new();
        for (partition, max_offset) in offsets {
            let _ = list.add_partition_offset(
                partition.topic(),
                partition.partition_number(),
                rdkafka::Offset::Offset(max_offset),
            );
        }

        let _ = consumer.store_offsets(&list);
    }

    fn commit_offsets(consumer: &StreamConsumer<BatchConsumerContext>) -> Result<()> {
        info!("Committing offsets...");

        // Commit only the safe offsets
        match consumer.commit_consumer_state(CommitMode::Async) {
            Ok(_) => {
                info!("Successfully committed offsets");
                Ok(())
            }
            Err(e) => {
                warn!("Failed to commit safe offsets: {e}");
                Err(e.into())
            }
        }
    }

    /// Consumes a batch of messages based on the configured batch size and timeout
    async fn consume_batch(
        stream: &mut MessageStream<'_, BatchConsumerContext>,
        shutdown_token: CancellationToken,
        batch_size: usize,
        batch_timeout: Duration,
    ) -> KafkaResult<Batch<T>> {
        let mut batch = Batch::new_with_size_hint(batch_size);
        let mut batch_complete = tokio::time::interval(batch_timeout);

        loop {
            tokio::select! {
                // Exit if the parent process signalled shutdown
                _ = shutdown_token.cancelled() => {
                    break;
                }

                // Exit if the batch timeout is reached before a full batch is collected
                _ = batch_complete.tick() => {
                    break;
                }

                // Try to get next message within the remaining batch time
                next_msg = stream.next() => {
                    match next_msg {
                        Some(Ok(borrowed_message)) => {
                            match KafkaMessage::<T>::from_borrowed_message(&borrowed_message) {
                                Ok(kafka_message) => {
                                    batch.push_message(kafka_message);
                                }
                                Err(e) => {
                                    let wrapped_err = anyhow!("Error deserializing message: {e}");
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
                            // KafkaError - for now, let's return these and fail fast
                            return Err(e);
                        }
                        None => {
                            // Stream ended - return what we have
                            break;
                        }
                    }
                    // if the batch is now at size, bail out and return it
                    if batch.message_count() >= batch_size {
                        break;
                    }
                }
            }
        }

        Ok(batch)
    }
}
