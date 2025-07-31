use futures::executor;
use rdkafka::consumer::{BaseConsumer, ConsumerContext, Rebalance};
use rdkafka::{ClientContext, TopicPartitionList};
use std::sync::Arc;
use tokio::runtime::Handle;
use tracing::{error, info, warn};

use super::rebalance_handler::RebalanceHandler;

/// Generic Kafka consumer context that delegates rebalance events to user-provided handlers
/// This handles all the rdkafka ConsumerContext complexity internally
pub struct GenericConsumerContext {
    rebalance_handler: Arc<dyn RebalanceHandler>,
    /// Handle to the async runtime for executing async callbacks from sync context
    rt_handle: Handle,
}

impl GenericConsumerContext {
    pub fn new(rebalance_handler: Arc<dyn RebalanceHandler>) -> Self {
        Self {
            rebalance_handler,
            rt_handle: Handle::current(),
        }
    }
}

impl ClientContext for GenericConsumerContext {}

impl ConsumerContext for GenericConsumerContext {
    fn pre_rebalance(&self, _base_consumer: &BaseConsumer<Self>, rebalance: &Rebalance) {
        info!("Pre-rebalance event: {:?}", rebalance);

        // Call user's pre-rebalance handler
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
                let handler = self.rebalance_handler.clone();

                // We need to block here to ensure revocation completes before rdkafka continues
                // This is critical for correctness
                if let Err(e) = executor::block_on(async move { 
                    handler.on_partitions_revoked(partitions).await 
                }) {
                    error!("Partition revocation handler failed: {}", e);
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
                let handler = self.rebalance_handler.clone();

                let mut partition_list = rdkafka::TopicPartitionList::new();
                for elem in partitions.elements() {
                    partition_list
                        .add_partition_offset(elem.topic(), elem.partition(), elem.offset())
                        .unwrap();
                }

                self.rt_handle.spawn(async move {
                    if let Err(e) = handler.on_partitions_assigned(&partition_list).await {
                        error!("Partition assignment handler failed: {}", e);
                    }
                });
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
    use crate::kafka::test_utils::create_test_consumer;
    use anyhow::Result;
    use async_trait::async_trait;
    use rdkafka::Offset;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    // Test implementation of RebalanceHandler that tracks calls
    #[derive(Default)]
    struct TestRebalanceHandler {
        assigned_count: AtomicUsize,
        revoked_count: AtomicUsize,
        pre_rebalance_count: AtomicUsize,
        post_rebalance_count: AtomicUsize,
        assigned_partitions: Mutex<Vec<(String, i32)>>,
        revoked_partitions: Mutex<Vec<(String, i32)>>,
    }

    #[async_trait]
    impl RebalanceHandler for TestRebalanceHandler {
        async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
            self.assigned_count.fetch_add(1, Ordering::SeqCst);

            let mut assigned = self.assigned_partitions.lock().unwrap();
            for elem in partitions.elements() {
                assigned.push((elem.topic().to_string(), elem.partition()));
            }

            Ok(())
        }

        async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
            self.revoked_count.fetch_add(1, Ordering::SeqCst);

            let mut revoked = self.revoked_partitions.lock().unwrap();
            for elem in partitions.elements() {
                revoked.push((elem.topic().to_string(), elem.partition()));
            }

            Ok(())
        }

        async fn on_pre_rebalance(&self) -> Result<()> {
            self.pre_rebalance_count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }

        async fn on_post_rebalance(&self) -> Result<()> {
            self.post_rebalance_count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

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
        let context = GenericConsumerContext::new(handler.clone());
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
        assert!(assigned.contains(&("test-topic-1".to_string(), 0)));
        assert!(assigned.contains(&("test-topic-1".to_string(), 1)));
        assert!(assigned.contains(&("test-topic-2".to_string(), 0)));
    }

    #[tokio::test]
    async fn test_partition_revocation_callback() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let context = GenericConsumerContext::new(handler.clone());
        let partitions = create_test_partition_list();

        // Simulate pre_rebalance with revocation
        let rebalance = Rebalance::Revoke(&partitions);
        let consumer = create_test_consumer(Arc::new(TestRebalanceHandler::default()));
        context.pre_rebalance(&consumer, &rebalance);

        // Give async tasks time to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;

        assert_eq!(handler.revoked_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.pre_rebalance_count.load(Ordering::SeqCst), 1);

        let revoked = handler.revoked_partitions.lock().unwrap();
        assert_eq!(revoked.len(), 3);
        assert!(revoked.contains(&("test-topic-1".to_string(), 0)));
        assert!(revoked.contains(&("test-topic-1".to_string(), 1)));
        assert!(revoked.contains(&("test-topic-2".to_string(), 0)));
    }

    #[tokio::test]
    async fn test_rebalance_error_handling() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let context = GenericConsumerContext::new(handler.clone());

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
        let context = GenericConsumerContext::new(handler);
        let partitions = create_test_partition_list();

        // Test successful commit - should not panic
        context.commit_callback(Ok(()), &partitions);
    }

    #[tokio::test]
    async fn test_commit_callback_failure() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let context = GenericConsumerContext::new(handler);
        let partitions = create_test_partition_list();

        // Test failed commit - should not panic
        let error = rdkafka::error::KafkaError::ConsumerCommit(
            rdkafka::error::RDKafkaErrorCode::InvalidPartitions,
        );
        context.commit_callback(Err(error), &partitions);
    }
}
