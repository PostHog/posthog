use anyhow::{Context, Result};
use async_trait::async_trait;
use rdkafka::TopicPartitionList;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{error, info, warn};

use crate::checkpoint::{CheckpointClient, CheckpointLoader};
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::rocksdb::deduplication_store::{DeduplicationStore, DeduplicationStoreConfig};

/// Deduplication-specific rebalance handler
/// This implements the RebalanceHandler trait to manage deduplication stores per partition
pub struct DeduplicationRebalanceHandler<C: CheckpointClient> {
    checkpoint_loader: CheckpointLoader<C>,
    stores: Arc<RwLock<HashMap<(String, i32), Arc<DeduplicationStore>>>>,
    store_config_template: DeduplicationStoreConfig,
}

impl<C: CheckpointClient> DeduplicationRebalanceHandler<C> {
    pub fn new(
        checkpoint_loader: CheckpointLoader<C>,
        store_config_template: DeduplicationStoreConfig,
    ) -> Self {
        Self {
            checkpoint_loader,
            stores: Arc::new(RwLock::new(HashMap::new())),
            store_config_template,
        }
    }

    /// Get a store for a specific topic/partition
    pub async fn get_store(&self, topic: &str, partition: i32) -> Option<Arc<DeduplicationStore>> {
        let stores = self.stores.read().await;
        stores.get(&(topic.to_string(), partition)).cloned()
    }

    /// Get all active stores (useful for shutdown)
    pub async fn get_all_stores(&self) -> HashMap<(String, i32), Arc<DeduplicationStore>> {
        self.stores.read().await.clone()
    }

    async fn initialize_partition_store(&self, topic: &str, partition: i32) -> Result<()> {
        let key = (topic.to_string(), partition);

        // Check if store already exists
        if self.stores.read().await.contains_key(&key) {
            info!(
                "Store already exists for topic {} partition {}",
                topic, partition
            );
            return Ok(());
        }

        info!(
            "Initializing store for topic {} partition {}",
            topic, partition
        );

        // Create partition-specific config
        let mut store_config = self.store_config_template.clone();
        store_config.path = store_config.path.join(format!("{}_{}", topic, partition));

        // Try to load latest checkpoint
        match self
            .checkpoint_loader
            .load_latest_checkpoint(topic, partition)
            .await
        {
            Ok(Some((_checkpoint_info, checkpoint_path))) => {
                info!(
                    "Loading checkpoint from {:?} for topic {} partition {}",
                    checkpoint_path, topic, partition
                );

                // Use checkpoint path as store path
                store_config.path = checkpoint_path;

                let store = DeduplicationStore::new(store_config, topic.to_string(), partition)
                    .with_context(|| {
                        format!(
                            "Failed to create store from checkpoint for topic {} partition {}",
                            topic, partition
                        )
                    })?;

                self.stores.write().await.insert(key, Arc::new(store));
                info!(
                    "Successfully loaded store from checkpoint for topic {} partition {}",
                    topic, partition
                );
            }
            Ok(None) => {
                info!(
                    "No checkpoint found for topic {} partition {}, creating new store",
                    topic, partition
                );

                let store = DeduplicationStore::new(store_config, topic.to_string(), partition)
                    .with_context(|| {
                        format!(
                            "Failed to create new store for topic {} partition {}",
                            topic, partition
                        )
                    })?;

                self.stores.write().await.insert(key, Arc::new(store));
                info!(
                    "Successfully created new store for topic {} partition {}",
                    topic, partition
                );
            }
            Err(e) => {
                warn!(
                    "Failed to load checkpoint for topic {} partition {}: {}. Creating new store.",
                    topic, partition, e
                );

                let store = DeduplicationStore::new(store_config, topic.to_string(), partition)
                    .with_context(|| {
                        format!(
                            "Failed to create fallback store for topic {} partition {}",
                            topic, partition
                        )
                    })?;

                self.stores.write().await.insert(key, Arc::new(store));
                info!(
                    "Successfully created fallback store for topic {} partition {}",
                    topic, partition
                );
            }
        }

        Ok(())
    }

    async fn cleanup_partition_store(&self, topic: &str, partition: i32) -> Result<()> {
        let key = (topic.to_string(), partition);

        if let Some(store) = self.stores.write().await.remove(&key) {
            info!(
                "Cleaned up store for topic {} partition {}",
                topic, partition
            );

            // TODO: Optionally trigger final checkpoint here
            // store.create_checkpoint(&final_checkpoint_path)?;

            drop(store); // Explicit drop to ensure cleanup
        } else {
            warn!(
                "No store found to cleanup for topic {} partition {}",
                topic, partition
            );
        }

        Ok(())
    }
}

#[async_trait]
impl<C: CheckpointClient> RebalanceHandler for DeduplicationRebalanceHandler<C> {
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
        info!(
            "Handling partition assignment for {} partitions",
            partitions.count()
        );

        // Extract partition info immediately to avoid Send issues
        let partition_infos: Vec<(String, i32)> = partitions
            .elements()
            .into_iter()
            .map(|elem| (elem.topic().to_string(), elem.partition()))
            .collect();

        for (topic, partition) in partition_infos {
            if let Err(e) = self.initialize_partition_store(&topic, partition).await {
                error!(
                    "Failed to initialize store for topic {} partition {}: {}",
                    topic, partition, e
                );
                // Continue with other partitions even if one fails
            }
        }

        info!("Completed partition assignment handling");
        Ok(())
    }

    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
        info!(
            "Handling partition revocation for {} partitions",
            partitions.count()
        );

        // Extract partition info immediately to avoid Send issues
        let partition_infos: Vec<(String, i32)> = partitions
            .elements()
            .into_iter()
            .map(|elem| (elem.topic().to_string(), elem.partition()))
            .collect();

        for (topic, partition) in partition_infos {
            if let Err(e) = self.cleanup_partition_store(&topic, partition).await {
                error!(
                    "Failed to cleanup store for topic {} partition {}: {}",
                    topic, partition, e
                );
                // Continue with other partitions even if one fails
            }
        }

        info!("Completed partition revocation handling");
        Ok(())
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        info!("Pre-rebalance: Preparing for partition changes");
        // Could add logic here to pause processing, flush buffers, etc.
        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        info!("Post-rebalance: Partition changes complete");
        // Could add logic here to resume processing, update metrics, etc.
        Ok(())
    }
}
