use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::{ClientContext, TopicPartitionList};
use std::sync::Arc;
use tokio::runtime::Handle;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::kafka::types::Partition;

use super::rebalance_handler::RebalanceHandler;
use super::tracker::InFlightTracker;

/// Events sent to the async rebalance worker
#[derive(Debug, Clone)]
pub enum RebalanceEvent {
    /// Partitions are being revoked
    Revoke(Vec<Partition>),
    /// Partitions have been assigned
    Assign(Vec<Partition>),
}

/// Stateful Kafka consumer context that coordinates with external state systems
/// This handles rebalance events and message tracking for sequential offset commits
pub struct StatefulConsumerContext {
    rebalance_handler: Arc<dyn RebalanceHandler>,
    /// Tracker for coordinating partition revocation with in-flight messages
    tracker: Arc<InFlightTracker>,
    /// Handle to the async runtime for executing async callbacks from sync context
    rt_handle: Handle,
    /// Channel to send rebalance events to async worker
    rebalance_tx: mpsc::UnboundedSender<RebalanceEvent>,
}

impl StatefulConsumerContext {
    pub fn new(
        rebalance_handler: Arc<dyn RebalanceHandler>,
        tracker: Arc<InFlightTracker>,
    ) -> Self {
        // Create channel for rebalance events
        let (tx, rx) = mpsc::unbounded_channel();

        // Start the async rebalance worker
        let worker_handler = rebalance_handler.clone();
        let worker_tracker = tracker.clone();
        Handle::current().spawn(async move {
            Self::rebalance_worker(rx, worker_tracker, worker_handler).await;
        });

        Self {
            rebalance_handler,
            tracker,
            rt_handle: Handle::current(),
            rebalance_tx: tx,
        }
    }

    /// Async worker that processes rebalance events
    async fn rebalance_worker(
        mut rx: mpsc::UnboundedReceiver<RebalanceEvent>,
        tracker: Arc<InFlightTracker>,
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

                    // Wait for all in-flight messages in these partitions to complete
                    let _final_offsets = tracker.wait_for_partition_completion(&partitions).await;
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

                    // Finalize revocation
                    tracker.finalize_revocation(&partitions).await;
                    info!(
                        "Rebalance worker: finalized revocation for {} partitions",
                        partitions.len()
                    );
                }
                RebalanceEvent::Assign(partitions) => {
                    info!(
                        "Rebalance worker: processing assignment for {} partitions",
                        partitions.len()
                    );

                    // Mark partitions as active
                    tracker.mark_partitions_active(&partitions).await;

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

impl ClientContext for StatefulConsumerContext {}

impl ConsumerContext for StatefulConsumerContext {
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

                // Fast, non-blocking fence operation
                let tracker_clone = self.tracker.clone();
                let partitions_clone = partitions.clone();
                self.rt_handle.spawn(async move {
                    tracker_clone.fence_partitions(&partitions_clone).await;
                });

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::test_utils::*;
    use rdkafka::Offset;
    use std::sync::atomic::Ordering;

    fn create_test_partition_list() -> TopicPartitionList {
        let mut list = TopicPartitionList::new();
        list.add_partition_offset("test-topic-1", 0, Offset::Beginning)
            .unwrap();
        list.add_partition_offset("test-topic-1", 1, Offset::Beginning)
            .unwrap();
        list.add_partition_offset("test-topic-2", 0, Offset::Beginning)
            .unwrap();
        list
    }

    #[tokio::test]
    async fn test_partition_assignment_callback() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler.clone(), tracker);
        let consumer = create_test_consumer(Arc::new(TestRebalanceHandler::default()));
        let partitions = create_test_partition_list();

        // Simulate post_rebalance with assignment
        let rebalance = Rebalance::Assign(&partitions);
        context.post_rebalance(&consumer, &rebalance);

        // Give async tasks time to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;

        assert_eq!(handler.assigned_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.post_rebalance_count.load(Ordering::SeqCst), 1);

        let assigned = handler.assigned_partitions.lock().unwrap();
        assert_eq!(assigned.len(), 3);
        assert!(assigned.contains(&Partition::new("test-topic-1".to_string(), 0)));
        assert!(assigned.contains(&Partition::new("test-topic-1".to_string(), 1)));
        assert!(assigned.contains(&Partition::new("test-topic-2".to_string(), 0)));
    }

    #[tokio::test]
    async fn test_partition_revocation_callback() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler.clone(), tracker);
        let partitions = create_test_partition_list();

        // Simulate pre_rebalance with revocation
        let rebalance = Rebalance::Revoke(&partitions);
        let consumer = create_test_consumer(Arc::new(TestRebalanceHandler::default()));
        context.pre_rebalance(&consumer, &rebalance);

        // Give async tasks time to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

        assert_eq!(handler.revoked_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.pre_rebalance_count.load(Ordering::SeqCst), 1);

        let revoked = handler.revoked_partitions.lock().unwrap();
        assert_eq!(revoked.len(), 3);
        assert!(revoked.contains(&Partition::new("test-topic-1".to_string(), 0)));
        assert!(revoked.contains(&Partition::new("test-topic-1".to_string(), 1)));
        assert!(revoked.contains(&Partition::new("test-topic-2".to_string(), 0)));
    }

    #[tokio::test]
    async fn test_rebalance_error_handling() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler.clone(), tracker);

        // Simulate rebalance error
        let error = rdkafka::error::KafkaError::ConsumerCommit(
            rdkafka::error::RDKafkaErrorCode::InvalidPartitions,
        );
        let rebalance = Rebalance::Error(error);

        // These should not panic
        let consumer = create_test_consumer(Arc::new(TestRebalanceHandler::default()));
        context.pre_rebalance(&consumer, &rebalance);
        context.post_rebalance(&consumer, &rebalance);

        // Give async tasks time to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;

        // Error events should still trigger pre/post rebalance callbacks
        assert_eq!(handler.pre_rebalance_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.post_rebalance_count.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn test_commit_callback_success() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler, tracker);
        let partitions = create_test_partition_list();

        // Test successful commit - should not panic
        context.commit_callback(Ok(()), &partitions);
    }

    #[tokio::test]
    async fn test_commit_callback_failure() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler, tracker);
        let partitions = create_test_partition_list();

        // Test failed commit - should not panic
        let error = rdkafka::error::KafkaError::ConsumerCommit(
            rdkafka::error::RDKafkaErrorCode::InvalidPartitions,
        );
        context.commit_callback(Err(error), &partitions);
    }

    #[tokio::test]
    async fn test_context_with_tracker_partition_revocation() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler.clone(), tracker.clone());
        let consumer = create_test_consumer(Arc::new(TestRebalanceHandler::default()));

        // Track some messages in different partitions
        let msg1 = rdkafka::message::OwnedMessage::new(
            Some("payload1".as_bytes().to_vec()),
            Some("key1".as_bytes().to_vec()),
            "test-topic-1".to_string(),
            rdkafka::message::Timestamp::now(),
            0,
            0,
            Some(rdkafka::message::OwnedHeaders::new()),
        );
        let msg2 = rdkafka::message::OwnedMessage::new(
            Some("payload2".as_bytes().to_vec()),
            Some("key2".as_bytes().to_vec()),
            "test-topic-1".to_string(),
            rdkafka::message::Timestamp::now(),
            0,
            1,
            Some(rdkafka::message::OwnedHeaders::new()),
        );

        // Need to acquire permits first for the new API
        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable1 = tracker.track_message(msg1, 100, permit1).await;
        let ackable2 = tracker.track_message(msg2, 100, permit2).await;

        // Verify messages are tracked and partition is active
        assert_eq!(tracker.in_flight_count().await, 2);
        assert!(
            tracker
                .is_partition_active(&Partition::new("test-topic-1".to_string(), 0))
                .await
        );

        // Create partition list for revocation
        let partitions = create_test_partition_list();
        let rebalance = rdkafka::consumer::Rebalance::Revoke(&partitions);

        // Call pre_rebalance - should fence immediately and return
        context.pre_rebalance(&consumer, &rebalance);

        // Give async tasks time to run
        tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;

        // Verify partition is now fenced (should happen immediately)
        assert!(
            !tracker
                .is_partition_active(&Partition::new("test-topic-1".to_string(), 0))
                .await
        );
        assert!(
            !tracker
                .is_partition_active(&Partition::new("test-topic-1".to_string(), 1))
                .await
        );

        // Messages should still be in-flight at this point
        assert_eq!(tracker.in_flight_count().await, 2);

        // Complete the messages to allow async worker to finish
        ackable1.ack().await;
        ackable2.ack().await;

        // Give async worker time to process
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

        // Verify all messages are now completed
        assert_eq!(tracker.in_flight_count().await, 0);

        // Handler should have been called by async worker
        assert_eq!(
            handler
                .revoked_count
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
        assert_eq!(
            handler
                .pre_rebalance_count
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
    }

    #[tokio::test]
    async fn test_context_with_tracker_partition_assignment() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler.clone(), tracker.clone());
        let consumer = create_test_consumer(Arc::new(TestRebalanceHandler::default()));

        // Initially fence some partitions
        let partitions = vec![
            Partition::new("test-topic-1".to_string(), 0),
            Partition::new("test-topic-1".to_string(), 1),
        ];
        tracker.fence_partitions(&partitions).await;

        // Verify partitions are fenced
        assert!(
            !tracker
                .is_partition_active(&Partition::new("test-topic-1".to_string(), 0))
                .await
        );
        assert!(
            !tracker
                .is_partition_active(&Partition::new("test-topic-1".to_string(), 1))
                .await
        );

        // Create partition list for assignment
        let partitions = create_test_partition_list();
        let rebalance = rdkafka::consumer::Rebalance::Assign(&partitions);

        // Simulate post_rebalance call
        context.post_rebalance(&consumer, &rebalance);

        // Give async tasks time to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

        // Verify partitions are now active
        assert!(
            tracker
                .is_partition_active(&Partition::new("test-topic-1".to_string(), 0))
                .await
        );
        assert!(
            tracker
                .is_partition_active(&Partition::new("test-topic-1".to_string(), 1))
                .await
        );

        // Verify rebalance handler was called
        assert_eq!(
            handler
                .assigned_count
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
        assert_eq!(
            handler
                .post_rebalance_count
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
    }

    #[tokio::test]
    async fn test_context_with_simplified_constructor() {
        // Test that the simplified constructor works correctly
        let handler = Arc::new(TestRebalanceHandler::default());
        let tracker = Arc::new(crate::kafka::InFlightTracker::new());
        let context = StatefulConsumerContext::new(handler.clone(), tracker);
        let consumer = create_test_consumer(Arc::new(TestRebalanceHandler::default()));

        let partitions = create_test_partition_list();

        // Should not panic when tracker is None
        let rebalance_revoke = rdkafka::consumer::Rebalance::Revoke(&partitions);
        context.pre_rebalance(&consumer, &rebalance_revoke);

        let rebalance_assign = rdkafka::consumer::Rebalance::Assign(&partitions);
        context.post_rebalance(&consumer, &rebalance_assign);

        // Give async tasks time to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

        // Verify handlers were still called
        assert_eq!(
            handler
                .revoked_count
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
        assert_eq!(
            handler
                .assigned_count
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
    }
}
