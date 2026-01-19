use anyhow::Result;
use async_trait::async_trait;
use rdkafka::TopicPartitionList;

/// Trait for handling Kafka consumer rebalance events
/// Users implement this to define their partition-specific logic
///
/// # Rebalance State Machine
///
/// ## Normal Revoke Flow
///
/// When partitions are revoked and NOT immediately re-assigned:
///
/// ```text
/// pre_rebalance(Revoke)
///     ├─► on_pre_rebalance()           [async, spawned]
///     ├─► setup_revoked_partitions()   [SYNC] - unregister stores from DashMap
///     └─► RebalanceEvent::Revoke sent to async worker
///
/// ... consumer waits ...
///
/// Async worker processes RebalanceEvent::Revoke:
///     └─► cleanup_revoked_partitions() [async] - shutdown workers, delete files
/// ```
///
/// ## Normal Assign Flow
///
/// When partitions are assigned:
///
/// ```text
/// post_rebalance(Assign)
///     ├─► setup_assigned_partitions()  [SYNC] - create partition workers
///     ├─► RebalanceEvent::Assign sent to async worker
///     └─► on_post_rebalance()          [async, spawned]
///
/// ... consumer stream resumes, messages start arriving ...
/// ... workers ALREADY EXIST, messages route successfully ...
///
/// Async worker processes RebalanceEvent::Assign:
///     └─► async_setup_assigned_partitions() [async] - pre-create stores, download checkpoints
/// ```
///
/// ## Rapid Revoke→Assign (Same Partition)
///
/// When a partition is revoked and immediately re-assigned (e.g., during rolling restart):
///
/// ```text
/// pre_rebalance(Revoke partition 0)
///     └─► setup_revoked_partitions()   - adds partition 0 to pending_cleanup set
///
/// post_rebalance(Assign partition 0)
///     └─► setup_assigned_partitions()  - REMOVES partition 0 from pending_cleanup
///                                       - reuses existing worker if present
///
/// Async worker processes RebalanceEvent::Revoke:
///     └─► cleanup_revoked_partitions() - checks pending_cleanup set
///                                       - partition 0 NOT in set → SKIPS cleanup!
///                                       - worker and store are preserved
/// ```
///
/// This ensures that rapid re-assignment doesn't accidentally delete the newly assigned
/// partition's worker or store.
///
/// # Method Pairs: Setup vs Cleanup
///
/// Each rebalance event has two phases:
///
/// **Setup methods** (`setup_*`) - Called synchronously within librdkafka callbacks.
/// These MUST be fast and non-blocking. They run BEFORE messages can arrive/stop.
/// - `setup_assigned_partitions`: Create workers before messages arrive
/// - `setup_revoked_partitions`: Unregister stores from map before revocation completes
///
/// **Cleanup methods** (`cleanup_*`) - Called asynchronously after callbacks return.
/// These can be slow and do I/O. They run in the background.
/// - `async_setup_assigned_partitions`: Post-assignment initialization (e.g., download checkpoints)
/// - `cleanup_revoked_partitions`: Drain queues, delete files
#[async_trait]
pub trait RebalanceHandler: Send + Sync {
    // ============================================
    // SETUP METHODS - Called within librdkafka callbacks
    // MUST be fast and non-blocking
    // ============================================

    /// Called synchronously when partitions are assigned.
    /// Runs WITHIN post_rebalance callback, BEFORE consumer stream resumes.
    ///
    /// Use for fast operations: creating workers, initializing maps.
    /// Default implementation does nothing.
    fn setup_assigned_partitions(&self, _partitions: &TopicPartitionList) {
        // Default implementation does nothing
    }

    /// Called synchronously when partitions are revoked.
    /// Runs WITHIN pre_rebalance callback, BEFORE revocation completes.
    ///
    /// Use for fast operations: removing stores from map, stopping new writes.
    /// Default implementation does nothing.
    fn setup_revoked_partitions(&self, _partitions: &TopicPartitionList) {
        // Default implementation does nothing
    }

    // ============================================
    // CLEANUP METHODS - Called after callbacks return
    // For slow operations like I/O, draining queues, etc.
    // ============================================

    /// Called asynchronously after partition assignment.
    /// Use for slow initialization: downloading checkpoints, warming caches.
    async fn async_setup_assigned_partitions(&self, partitions: &TopicPartitionList) -> Result<()>;

    /// Called asynchronously after partition revocation.
    /// Use for slow cleanup: draining worker queues, uploading checkpoints, deleting files.
    async fn cleanup_revoked_partitions(&self, partitions: &TopicPartitionList) -> Result<()>;

    /// Called before any rebalance operation begins
    async fn on_pre_rebalance(&self) -> Result<()> {
        Ok(())
    }

    /// Called after rebalance operation completes
    async fn on_post_rebalance(&self) -> Result<()> {
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
        fn setup_assigned_partitions(&self, partitions: &TopicPartitionList) {
            self.assigned_count.fetch_add(1, Ordering::SeqCst);

            let mut assigned = self.assigned_partitions.lock().unwrap();
            for elem in partitions.elements() {
                assigned.push(Partition::from(elem));
            }
        }

        fn setup_revoked_partitions(&self, partitions: &TopicPartitionList) {
            self.revoked_count.fetch_add(1, Ordering::SeqCst);

            let mut revoked = self.revoked_partitions.lock().unwrap();
            for elem in partitions.elements() {
                revoked.push(Partition::from(elem));
            }
        }

        async fn async_setup_assigned_partitions(
            &self,
            _partitions: &TopicPartitionList,
        ) -> Result<()> {
            Ok(())
        }

        async fn cleanup_revoked_partitions(&self, _partitions: &TopicPartitionList) -> Result<()> {
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

        // Test partition assignment (sync setup)
        handler.setup_assigned_partitions(&partitions);

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

        // Test partition revocation (sync setup)
        handler.setup_revoked_partitions(&partitions);

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

        // Simulate full rebalance flow:
        // 1. Pre-rebalance (async, but runs first)
        handler.on_pre_rebalance().await.unwrap();
        // 2. Revoke setup (sync, within callback)
        handler.setup_revoked_partitions(&partitions);
        // 3. Assign setup (sync, within callback)
        handler.setup_assigned_partitions(&partitions);
        // 4. Post-rebalance (async)
        handler.on_post_rebalance().await.unwrap();
        // 5. Revoke cleanup (async, in background)
        handler
            .cleanup_revoked_partitions(&partitions)
            .await
            .unwrap();
        // 6. Assign cleanup (async, in background)
        handler
            .async_setup_assigned_partitions(&partitions)
            .await
            .unwrap();

        assert_eq!(handler.pre_rebalance_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.revoked_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.assigned_count.load(Ordering::SeqCst), 1);
        assert_eq!(handler.post_rebalance_count.load(Ordering::SeqCst), 1);
    }
}
