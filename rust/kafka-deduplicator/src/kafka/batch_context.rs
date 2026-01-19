use std::sync::Arc;
use tokio::runtime::Handle;
use tokio::sync::mpsc;

use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::{ClientContext, TopicPartitionList};
use tracing::{error, info, warn};

/// Events sent to the async rebalance worker
#[derive(Debug, Clone)]
pub enum RebalanceEvent {
    /// Partitions are being revoked
    Revoke(Vec<Partition>),
    /// Partitions have been assigned
    Assign(Vec<Partition>),
}

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

    /// Async worker that processes rebalance cleanup events
    ///
    /// Note: This worker only handles CLEANUP operations (slow I/O).
    /// The SETUP operations (creating workers, removing stores from map) are done
    /// synchronously within the librdkafka callbacks to ensure they complete
    /// before messages can arrive/stop.
    async fn rebalance_worker(
        mut rx: mpsc::UnboundedReceiver<RebalanceEvent>,
        handler: Arc<dyn RebalanceHandler>,
    ) {
        info!("Starting rebalance cleanup worker");

        while let Some(event) = rx.recv().await {
            match event {
                RebalanceEvent::Revoke(partitions) => {
                    info!(
                        "Rebalance worker: cleaning up {} revoked partitions",
                        partitions.len()
                    );

                    // Create TopicPartitionList for handler
                    let mut tpl = TopicPartitionList::new();
                    for partition in &partitions {
                        tpl.add_partition(partition.topic(), partition.partition_number());
                    }

                    // Call cleanup handler (drains queues, deletes files)
                    // Note: setup_revoked_partitions was already called synchronously
                    if let Err(e) = handler.cleanup_revoked_partitions(&tpl).await {
                        error!("Partition revocation cleanup failed: {}", e);
                    }
                }
                RebalanceEvent::Assign(partitions) => {
                    info!(
                        "Rebalance worker: cleaning up {} assigned partitions",
                        partitions.len()
                    );

                    // Create TopicPartitionList for handler
                    let mut tpl = TopicPartitionList::new();
                    for partition in &partitions {
                        tpl.add_partition(partition.topic(), partition.partition_number());
                    }

                    // Call cleanup handler (downloads checkpoints, etc.)
                    // Note: setup_assigned_partitions was already called synchronously
                    if let Err(e) = handler.async_setup_assigned_partitions(&tpl).await {
                        error!("Partition assignment cleanup failed: {}", e);
                    }
                }
            }
        }

        info!("Rebalance cleanup worker shutting down");
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

                // SYNC: Call setup handler directly within callback
                // This removes stores from DashMap BEFORE revocation completes
                // ensuring no new stores can be created during shutdown
                self.rebalance_handler.setup_revoked_partitions(partitions);

                // ASYNC: Send cleanup event to worker for slow operations
                // (draining queues, deleting files)
                let partitions: Vec<Partition> = partitions
                    .elements()
                    .into_iter()
                    .map(Partition::from)
                    .collect();

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

                // SYNC: Call setup handler directly within callback
                // This creates partition workers BEFORE messages can arrive
                self.rebalance_handler.setup_assigned_partitions(partitions);

                info!(
                    "📋 Total partitions assigned: {} partitions",
                    partitions.count()
                );

                // ASYNC: Send cleanup event to worker for slow operations
                // (downloading checkpoints, etc.)
                let partitions: Vec<Partition> = partitions
                    .elements()
                    .into_iter()
                    .map(Partition::from)
                    .collect();

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
