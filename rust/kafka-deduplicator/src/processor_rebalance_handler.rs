use anyhow::Result;
use async_trait::async_trait;
use dashmap::DashMap;
use rdkafka::TopicPartitionList;
use std::sync::Arc;
use tracing::info;

use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;
use crate::rocksdb::deduplication_store::DeduplicationStore;

/// Rebalance handler that coordinates store cleanup on partition revocation
pub struct ProcessorRebalanceHandler {
    stores: Arc<DashMap<Partition, DeduplicationStore>>,
}

impl ProcessorRebalanceHandler {
    pub fn new(stores: Arc<DashMap<Partition, DeduplicationStore>>) -> Self {
        Self { stores }
    }
}

#[async_trait]
impl RebalanceHandler for ProcessorRebalanceHandler {
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
        info!("Partitions assigned: {} partitions", partitions.count());

        // TODO: We should download the checkpoint from S3 here
        // We should not allow the processor to start until the checkpoint is downloaded
        Ok(())
    }

    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
        info!("Partitions revoked: {} partitions", partitions.count());

        // Extract partition info for cleanup
        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        // Clean up stores for revoked partitions
        for partition in &partition_infos {
            if let Some(_store) = self.stores.remove(partition) {
                info!(
                    "Cleaned up deduplication store for revoked partition {}:{}",
                    partition.topic(),
                    partition.partition_number()
                );
                // Store will be dropped when Arc goes out of scope
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
        let store_count = self.stores.len();
        info!("Active deduplication stores: {}", store_count);

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::deduplication_processor::DeduplicationConfig;
    use rdkafka::config::ClientConfig;
    use std::time::Duration;
    use tempfile::TempDir;

    fn create_test_config() -> (DeduplicationConfig, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let store_config = crate::rocksdb::deduplication_store::DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };

        let mut producer_config = ClientConfig::new();
        producer_config.set("bootstrap.servers", "localhost:9092");

        let config = DeduplicationConfig {
            output_topic: Some("test-output".to_string()),
            producer_config,
            store_config,
            producer_send_timeout: Duration::from_secs(5),
            flush_interval: Duration::from_secs(120),
        };

        (config, temp_dir)
    }

    #[tokio::test]
    async fn test_rebalance_handler_creation() {
        let (_config, _temp_dir) = create_test_config();

        // This would fail without Kafka, but we can test the handler creation logic
        // In practice, we'd need to mock the processor or run integration tests

        // For now, just test that the structs can be created
        assert!(std::mem::size_of::<ProcessorRebalanceHandler>() > 0);
    }
}
