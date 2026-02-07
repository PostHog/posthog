use std::sync::Arc;
use tokio::runtime::Handle;
use tokio::sync::mpsc;

use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;
use crate::metrics_const::REBALANCE_EMPTY_SKIPPED;
use rdkafka::consumer::{BaseConsumer, Consumer, ConsumerContext, Rebalance};
use rdkafka::{ClientContext, TopicPartitionList};
use tracing::{debug, error, info, warn};

/// Events sent to the async rebalance worker
#[derive(Debug, Clone)]
pub enum RebalanceEvent {
    /// Partitions are being revoked - includes partition list for worker shutdown
    Revoke(Vec<Partition>),
    /// Partitions have been assigned - handler uses get_owned_partitions() for definitive list
    Assign,
}

/// Commands sent from rebalance handler to consumer for partition control
#[derive(Debug)]
pub enum ConsumerCommand {
    /// Resume consumption for the specified partitions (after checkpoint import completes)
    Resume(TopicPartitionList),
}

/// Sender for consumer commands - passed to rebalance handler
pub type ConsumerCommandSender = mpsc::UnboundedSender<ConsumerCommand>;
/// Receiver for consumer commands - held by BatchConsumer
pub type ConsumerCommandReceiver = mpsc::UnboundedReceiver<ConsumerCommand>;

pub struct BatchConsumerContext {
    rebalance_handler: Arc<dyn RebalanceHandler>,
    /// Handle to the async runtime for executing async callbacks from sync context
    rt_handle: Handle,
    /// Channel to send rebalance events to async worker
    rebalance_tx: mpsc::UnboundedSender<RebalanceEvent>,
}
impl BatchConsumerContext {
    pub fn new(
        rebalance_handler: Arc<dyn RebalanceHandler>,
        consumer_command_tx: ConsumerCommandSender,
    ) -> Self {
        // Create channel for rebalance events
        let (tx, rx) = mpsc::unbounded_channel();

        // Start the async rebalance worker
        let worker_handler = rebalance_handler.clone();
        Handle::current().spawn(async move {
            Self::rebalance_worker(rx, worker_handler, consumer_command_tx).await;
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
        consumer_command_tx: ConsumerCommandSender,
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

                    // Call cleanup handler (drains queues, clears offsets)
                    // Note: setup_revoked_partitions was already called synchronously
                    // Note: File deletion happens in finalize_rebalance_cycle at end of cycle
                    if let Err(e) = handler.cleanup_revoked_partitions(&tpl).await {
                        error!("Partition revocation cleanup failed: {}", e);
                    }
                }
                RebalanceEvent::Assign => {
                    info!("Rebalance worker: processing assign event (async)");

                    // Call async setup handler (downloads checkpoints, creates stores)
                    // Handler uses rebalance_tracker.get_owned_partitions() for the definitive list
                    // Note: setup_assigned_partitions was already called synchronously
                    // Note: Partitions were paused in post_rebalance, will be resumed after this completes
                    // Note: Resume is now handled inside async_setup_assigned_partitions,
                    // only when all overlapping rebalances are complete (counter == 0)
                    if let Err(e) = handler
                        .async_setup_assigned_partitions(&consumer_command_tx)
                        .await
                    {
                        // This error only occurs if the consumer command channel is broken.
                        // Resume is handled by async_setup_assigned_partitions when appropriate.
                        error!("Partition assignment async setup failed: {}", e);
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
                // Short-circuit for empty TPL (cooperative-sticky sends these frequently)
                // With cooperative-sticky protocol, the broker triggers rebalances for all
                // consumers when any group membership changes, even if partitions don't move.
                if partitions.count() == 0 {
                    debug!("Skipping empty revoke rebalance (cooperative-sticky no-op)");
                    metrics::counter!(REBALANCE_EMPTY_SKIPPED, "event_type" => "revoke")
                        .increment(1);
                    return;
                }

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

    fn post_rebalance(&self, base_consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        info!("Post-rebalance event: {:?}", rebalance);

        // Handle partition assignment if applicable
        match rebalance {
            Rebalance::Assign(partitions) => {
                // Short-circuit for empty TPL (cooperative-sticky sends these frequently)
                // With cooperative-sticky protocol, the broker triggers rebalances for all
                // consumers when any group membership changes, even if partitions don't move.
                if partitions.count() == 0 {
                    debug!("Skipping empty assign rebalance (cooperative-sticky no-op)");
                    metrics::counter!(REBALANCE_EMPTY_SKIPPED, "event_type" => "assign")
                        .increment(1);
                    return;
                }

                info!("Assigned {} partitions", partitions.count());

                // PAUSE partitions IMMEDIATELY to prevent message delivery
                // until checkpoint import completes. This fixes the race condition
                // where workers create fresh stores before checkpoints are imported.
                // The partitions will be resumed after async_setup_assigned_partitions
                // completes via a ConsumerCommand::Resume.
                if let Err(e) = base_consumer.pause(partitions) {
                    error!(
                        "Failed to pause {} newly assigned partitions: {}",
                        partitions.count(),
                        e
                    );
                } else {
                    info!(
                        "Paused {} newly assigned partitions - will resume after checkpoint import",
                        partitions.count()
                    );
                }

                // SYNC: Call setup handler directly within callback
                // This creates partition workers BEFORE messages can arrive
                self.rebalance_handler.setup_assigned_partitions(partitions);

                info!(
                    "Total partitions assigned: {} partitions (paused until stores ready)",
                    partitions.count()
                );

                // ASYNC: Send event to worker for slow operations
                // (downloading checkpoints, creating stores, then RESUME)
                // Handler uses rebalance_tracker.get_owned_partitions() for definitive list
                if let Err(e) = self.rebalance_tx.send(RebalanceEvent::Assign) {
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

#[cfg(test)]
mod tests {
    use rdkafka::{Offset, TopicPartitionList};

    /// Verify that empty TopicPartitionList has count() == 0.
    /// This is the behavior we rely on for short-circuiting empty rebalances.
    #[test]
    fn test_empty_topic_partition_list_count_is_zero() {
        let tpl = TopicPartitionList::new();
        assert_eq!(tpl.count(), 0, "Empty TPL should have count == 0");
    }

    /// Verify that non-empty TopicPartitionList has count() > 0.
    #[test]
    fn test_non_empty_topic_partition_list_count() {
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        assert_eq!(
            tpl.count(),
            1,
            "TPL with one partition should have count == 1"
        );

        tpl.add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        assert_eq!(
            tpl.count(),
            2,
            "TPL with two partitions should have count == 2"
        );
    }

    /// Verify that our short-circuit condition works correctly.
    /// This simulates the check we do in pre_rebalance and post_rebalance.
    #[test]
    fn test_empty_tpl_short_circuit_condition() {
        let empty_tpl = TopicPartitionList::new();
        let should_skip = empty_tpl.count() == 0;
        assert!(should_skip, "Empty TPL should trigger short-circuit");

        let mut non_empty_tpl = TopicPartitionList::new();
        non_empty_tpl
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        let should_not_skip = non_empty_tpl.count() == 0;
        assert!(
            !should_not_skip,
            "Non-empty TPL should not trigger short-circuit"
        );
    }
}
