use anyhow::Result;
use async_trait::async_trait;
use rdkafka::TopicPartitionList;

/// Trait for handling Kafka consumer rebalance events
/// Users implement this to define their partition-specific logic
#[async_trait]
pub trait RebalanceHandler: Send + Sync {
    /// Called when partitions are assigned to this consumer
    /// This happens after Kafka coordinator assigns partitions during rebalance
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()>;

    /// Called when partitions are revoked from this consumer  
    /// This happens before Kafka coordinator revokes partitions during rebalance
    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()>;

    /// Called before any rebalance operation begins
    /// Use this for preparation work before partition changes
    async fn on_pre_rebalance(&self) -> Result<()> {
        // Default implementation does nothing
        Ok(())
    }

    /// Called after rebalance operation completes
    /// Use this for cleanup or post-rebalance initialization
    async fn on_post_rebalance(&self) -> Result<()> {
        // Default implementation does nothing
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::types::Partition;
    use rdkafka::Offset;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    // Test implementation of RebalanceHandler
    #[derive(Default)]
    struct TestRebalanceHandler {
        assigned_count: AtomicUsize,
        revoked_count: AtomicUsize,
        pre_rebalance_count: AtomicUsize,
        post_rebalance_count: AtomicUsize,
        assigned_partitions: std::sync::Mutex<Vec<Partition>>,
        revoked_partitions: std::sync::Mutex<Vec<Partition>>,
    }

    #[async_trait]
    impl RebalanceHandler for TestRebalanceHandler {
        async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
            self.assigned_count.fetch_add(1, Ordering::SeqCst);

            let mut assigned = self.assigned_partitions.lock().unwrap();
            for elem in partitions.elements() {
                assigned.push(Partition::from(elem));
            }

            Ok(())
        }

        async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
            self.revoked_count.fetch_add(1, Ordering::SeqCst);

            let mut revoked = self.revoked_partitions.lock().unwrap();
            for elem in partitions.elements() {
                revoked.push(Partition::from(elem));
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
    async fn test_rebalance_handler_partition_assignment() {
        let handler = TestRebalanceHandler::default();
        let partitions = create_test_partition_list();

        // Test partition assignment
        handler.on_partitions_assigned(&partitions).await.unwrap();

        assert_eq!(handler.assigned_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.revoked_count.load(Ordering::SeqCst), 0);

        let assigned = handler.assigned_partitions.lock().unwrap();
        assert_eq!(assigned.len(), 3);
        assert!(assigned.contains(&Partition::new("test-topic-1".to_string(), 0)));
        assert!(assigned.contains(&Partition::new("test-topic-1".to_string(), 1)));
        assert!(assigned.contains(&Partition::new("test-topic-2".to_string(), 0)));
    }

    #[tokio::test]
    async fn test_rebalance_handler_partition_revocation() {
        let handler = TestRebalanceHandler::default();
        let partitions = create_test_partition_list();

        // Test partition revocation
        handler.on_partitions_revoked(&partitions).await.unwrap();

        assert_eq!(handler.assigned_count.load(Ordering::SeqCst), 0);
        assert_eq!(handler.revoked_count.load(Ordering::SeqCst), 1);

        let revoked = handler.revoked_partitions.lock().unwrap();
        assert_eq!(revoked.len(), 3);
        assert!(revoked.contains(&Partition::new("test-topic-1".to_string(), 0)));
        assert!(revoked.contains(&Partition::new("test-topic-1".to_string(), 1)));
        assert!(revoked.contains(&Partition::new("test-topic-2".to_string(), 0)));
    }

    #[tokio::test]
    async fn test_rebalance_handler_pre_post_callbacks() {
        let handler = TestRebalanceHandler::default();

        // Test pre and post rebalance callbacks
        handler.on_pre_rebalance().await.unwrap();
        handler.on_post_rebalance().await.unwrap();

        assert_eq!(handler.pre_rebalance_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.post_rebalance_count.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn test_full_rebalance_flow() {
        let handler = Arc::new(TestRebalanceHandler::default());
        let partitions = create_test_partition_list();

        // Simulate full rebalance flow
        handler.on_pre_rebalance().await.unwrap();
        handler.on_partitions_revoked(&partitions).await.unwrap();
        handler.on_partitions_assigned(&partitions).await.unwrap();
        handler.on_post_rebalance().await.unwrap();

        assert_eq!(handler.pre_rebalance_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.revoked_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.assigned_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.post_rebalance_count.load(Ordering::SeqCst), 1);
    }
}
