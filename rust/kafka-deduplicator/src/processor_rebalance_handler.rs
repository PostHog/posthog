use anyhow::Result;
use async_trait::async_trait;
use rdkafka::TopicPartitionList;
use std::sync::Arc;
use tracing::{error, info};

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::partition_router::{shutdown_workers, PartitionRouter};
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;
use crate::store_manager::StoreManager;

/// Rebalance handler that coordinates store cleanup and partition workers
pub struct ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    store_manager: Arc<StoreManager>,
    router: Option<Arc<PartitionRouter<T, P>>>,
}

impl<T, P> ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    pub fn new(store_manager: Arc<StoreManager>) -> Self {
        Self {
            store_manager,
            router: None,
        }
    }

    pub fn with_router(
        store_manager: Arc<StoreManager>,
        router: Arc<PartitionRouter<T, P>>,
    ) -> Self {
        Self {
            store_manager,
            router: Some(router),
        }
    }
}

#[async_trait]
impl<T, P> RebalanceHandler for ProcessorRebalanceHandler<T, P>
where
    T: Send + Sync + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        info!("Partitions assigned: {} partitions", partition_infos.len());

        // Create partition workers if router is configured
        if let Some(ref router) = self.router {
            router.add_partitions(&partition_infos);
            info!(
                "Created partition workers. Active workers: {}",
                router.worker_count()
            );
        }

        // TODO: We should download the checkpoint from S3 here
        // We should not allow the processor to start until the checkpoint is downloaded
        Ok(())
    }

    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        info!("Partitions revoked: {} partitions", partition_infos.len());

        // IMPORTANT: Remove stores BEFORE shutting down workers.
        // This prevents a race condition where:
        // 1. Worker is processing messages during shutdown
        // 2. Worker calls store_manager.get_or_create() which creates a new store
        // 3. store_manager.remove() deletes the directory
        // 4. Worker's write fails with "No such file or directory"
        //
        // By removing stores first, any in-flight worker operations will fail
        // gracefully with "store not found" rather than filesystem errors.
        for partition in &partition_infos {
            // Only remove from DashMap, don't delete files yet
            // Files will be deleted after workers are shut down
            self.store_manager
                .remove_from_map(partition.topic(), partition.partition_number());
        }

        // Shutdown partition workers - they may still have queued messages
        // but won't be able to create new stores since we removed them above
        if let Some(ref router) = self.router {
            let workers = router.remove_partitions(&partition_infos);
            shutdown_workers(workers).await;
            info!(
                "Shut down partition workers. Active workers: {}",
                router.worker_count()
            );
        }

        // Now safe to delete files - workers are shut down and can't write anymore
        for partition in &partition_infos {
            if let Err(e) = self
                .store_manager
                .delete_partition_files(partition.topic(), partition.partition_number())
            {
                error!(
                    "Failed to delete files for revoked partition {}:{}: {}",
                    partition.topic(),
                    partition.partition_number(),
                    e
                );
            } else {
                info!(
                    "Cleaned up deduplication store files for revoked partition {}:{}",
                    partition.topic(),
                    partition.partition_number()
                );
            }
        }

        Ok(())
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        info!("Pre-rebalance: Preparing for partition changes");
        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        info!("Post-rebalance: Partition changes complete");

        // Log current stats
        let store_count = self.store_manager.stores().len();
        info!("Active deduplication stores: {}", store_count);

        if let Some(ref router) = self.router {
            info!("Active partition workers: {}", router.worker_count());
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::batch_message::KafkaMessage;
    use crate::kafka::partition_router::PartitionRouterConfig;
    use crate::store::DeduplicationStoreConfig;
    use rdkafka::Offset;
    use tempfile::TempDir;

    struct TestProcessor;

    #[async_trait]
    impl BatchConsumerProcessor<String> for TestProcessor {
        async fn process_batch(&self, _messages: Vec<KafkaMessage<String>>) -> Result<()> {
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_rebalance_handler_creation() {
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));

        // Test handler without router
        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(store_manager.clone());
        assert!(handler.router.is_none());

        // Test handler with router
        let processor = Arc::new(TestProcessor);
        let router = Arc::new(PartitionRouter::new(
            processor,
            PartitionRouterConfig::default(),
        ));
        let handler_with_router =
            ProcessorRebalanceHandler::with_router(store_manager, router.clone());
        assert!(handler_with_router.router.is_some());
    }

    #[tokio::test]
    async fn test_rebalance_handler_manages_workers() {
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));
        let processor = Arc::new(TestProcessor);
        let router = Arc::new(PartitionRouter::new(
            processor,
            PartitionRouterConfig::default(),
        ));

        let handler = ProcessorRebalanceHandler::with_router(store_manager, router.clone());

        // Initially no workers
        assert_eq!(router.worker_count(), 0);

        // Assign partitions
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();

        handler.on_partitions_assigned(&partitions).await.unwrap();
        assert_eq!(router.worker_count(), 2);

        // Revoke one partition
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.on_partitions_revoked(&revoked).await.unwrap();
        assert_eq!(router.worker_count(), 1);

        // Cleanup
        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_rebalance_removes_stores_before_workers_shutdown() {
        // This test verifies the fix for the race condition where:
        // 1. Worker is processing messages during shutdown
        // 2. Worker calls store_manager.get_or_create() which would create a new store
        // 3. store_manager.remove() deletes the directory
        // 4. Worker's write fails with "No such file or directory"
        //
        // The fix ensures stores are removed from the map BEFORE workers are shut down,
        // so workers cannot create new stores during shutdown.

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));
        let processor = Arc::new(TestProcessor);
        let router = Arc::new(PartitionRouter::new(
            processor,
            PartitionRouterConfig::default(),
        ));

        let handler = ProcessorRebalanceHandler::with_router(store_manager.clone(), router.clone());

        // Assign partition and create a store
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.on_partitions_assigned(&partitions).await.unwrap();
        assert_eq!(router.worker_count(), 1);

        // Create a store for the partition (simulating what happens during processing)
        store_manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(store_manager.get_active_store_count(), 1);

        // Revoke the partition
        handler.on_partitions_revoked(&partitions).await.unwrap();

        // After revocation:
        // - Worker should be shut down
        // - Store should be removed from map
        // - Files should be deleted
        assert_eq!(router.worker_count(), 0);
        assert_eq!(store_manager.get_active_store_count(), 0);

        // Verify files are deleted
        let partition_dir = temp_dir.path().join("test-topic_0");
        assert!(
            !partition_dir.exists(),
            "Partition directory should be deleted after revocation"
        );
    }

    #[tokio::test]
    async fn test_rebalance_store_not_found_during_shutdown() {
        // This test verifies that after stores are removed from the map,
        // any attempt to get_or_create will return an error rather than
        // creating a new store that would be immediately deleted.

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));

        // Create a store
        store_manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(store_manager.get_active_store_count(), 1);

        // Remove from map only (simulating first step of revocation)
        store_manager.remove_from_map("test-topic", 0);
        assert_eq!(store_manager.get_active_store_count(), 0);

        // Verify we can still create a new store if needed
        // (this would happen if partition is re-assigned)
        store_manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(store_manager.get_active_store_count(), 1);

        // Cleanup
        store_manager.remove("test-topic", 0).unwrap();
    }

    #[tokio::test]
    async fn test_delete_partition_files_after_remove_from_map() {
        // Test that delete_partition_files works correctly after remove_from_map

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));

        // Create a store (this creates the directory)
        store_manager.get_or_create("test-topic", 0).await.unwrap();

        let partition_dir = temp_dir.path().join("test-topic_0");
        assert!(partition_dir.exists(), "Partition directory should exist");

        // Remove from map (store is dropped, RocksDB is closed)
        store_manager.remove_from_map("test-topic", 0);
        assert_eq!(store_manager.get_active_store_count(), 0);

        // Directory should still exist (files not deleted yet)
        assert!(
            partition_dir.exists(),
            "Partition directory should still exist after remove_from_map"
        );

        // Now delete the files
        store_manager
            .delete_partition_files("test-topic", 0)
            .unwrap();

        // Directory should be deleted
        assert!(
            !partition_dir.exists(),
            "Partition directory should be deleted after delete_partition_files"
        );
    }
}
