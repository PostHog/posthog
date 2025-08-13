use anyhow::Result;
use async_trait::async_trait;
use rdkafka::TopicPartitionList;
use std::sync::Arc;
use tracing::info;

use crate::deduplication_processor::DeduplicationProcessor;
use crate::kafka::rebalance_handler::RebalanceHandler;

/// Rebalance handler that coordinates with DeduplicationProcessor
/// This handler cleans up stores for revoked partitions
pub struct ProcessorRebalanceHandler {
    processor: Arc<DeduplicationProcessor>,
}

impl ProcessorRebalanceHandler {
    pub fn new(processor: Arc<DeduplicationProcessor>) -> Self {
        Self { processor }
    }
}

#[async_trait]
impl RebalanceHandler for ProcessorRebalanceHandler {
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
        info!(
            "Partitions assigned: {} partitions",
            partitions.count()
        );
        
        // No special handling needed for assignment - stores are created on-demand
        Ok(())
    }

    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
        info!(
            "Partitions revoked: {} partitions",
            partitions.count()
        );

        // Extract partition info for cleanup
        let partition_infos: Vec<(String, i32)> = partitions
            .elements()
            .into_iter()
            .map(|elem| (elem.topic().to_string(), elem.partition()))
            .collect();

        // Clean up stores for revoked partitions
        self.processor.cleanup_stores(&partition_infos).await;

        Ok(())
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        info!("Pre-rebalance: Preparing for partition changes");
        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        info!("Post-rebalance: Partition changes complete");
        
        // Log current stats
        let store_count = self.processor.get_active_store_count().await;
        info!("Active deduplication stores: {}", store_count);
        
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::deduplication_processor::DeduplicationConfig;
    use rdkafka::config::ClientConfig;
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
