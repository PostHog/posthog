use std::sync::Arc;
use tokio::runtime::Handle;
use tokio::sync::mpsc;

use crate::kafka::types::Partition;
use crate::kafka::{rebalance_handler::RebalanceHandler, stateful_context::RebalanceEvent};
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::{ClientContext, TopicPartitionList};
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
