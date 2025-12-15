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

        // Shutdown partition workers if router is configured
        if let Some(ref router) = self.router {
            let workers = router.remove_partitions(&partition_infos);
            shutdown_workers(workers).await;
            info!(
                "Shut down partition workers. Active workers: {}",
                router.worker_count()
            );
        }

        // Clean up stores for revoked partitions
        for partition in &partition_infos {
            if let Err(e) = self
                .store_manager
                .remove(partition.topic(), partition.partition_number())
            {
                error!(
                    "Failed to remove store for revoked partition {}:{}: {}",
                    partition.topic(),
                    partition.partition_number(),
                    e
                );
            } else {
                info!(
                    "Cleaned up deduplication store and files for revoked partition {}:{}",
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
}
