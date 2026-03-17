use std::sync::Arc;

use async_trait::async_trait;
use personhog_coordination::error::Result;
use personhog_coordination::pod::HandoffHandler;
use tracing::info;

use crate::cache::PartitionedCache;

/// Tracks which partitions this leader pod owns and handles
/// partition handoff lifecycle (warming and releasing).
pub struct LeaderHandoffHandler {
    cache: Arc<PartitionedCache>,
}

impl LeaderHandoffHandler {
    pub fn new(cache: Arc<PartitionedCache>) -> Self {
        Self { cache }
    }

    /// Check if this leader pod owns the given partition.
    pub fn owns_partition(&self, partition: u32) -> bool {
        self.cache.has_partition(partition)
    }
}

#[async_trait]
impl HandoffHandler for LeaderHandoffHandler {
    async fn warm_partition(&self, partition: u32) -> Result<()> {
        info!(partition, "warming partition cache");

        // For the PoC, warming creates an empty per-partition cache.
        // In production this would also consume Kafka to rebuild state.
        self.cache.create_partition(partition);

        info!(partition, "partition warmed");
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        info!(partition, "releasing partition");

        // Dropping the partition cache evicts all entries for this partition.
        self.cache.drop_partition(partition);

        info!(partition, "partition released");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn warm_partition_adds_ownership() {
        let cache = Arc::new(PartitionedCache::new(100));
        let handler = LeaderHandoffHandler::new(cache);

        assert!(!handler.owns_partition(42));
        handler.warm_partition(42).await.unwrap();
        assert!(handler.owns_partition(42));
    }

    #[tokio::test]
    async fn release_partition_removes_ownership() {
        let cache = Arc::new(PartitionedCache::new(100));
        let handler = LeaderHandoffHandler::new(cache);

        handler.warm_partition(42).await.unwrap();
        assert!(handler.owns_partition(42));

        handler.release_partition(42).await.unwrap();
        assert!(!handler.owns_partition(42));
    }

    #[tokio::test]
    async fn multiple_partitions() {
        let cache = Arc::new(PartitionedCache::new(100));
        let handler = LeaderHandoffHandler::new(cache);

        handler.warm_partition(1).await.unwrap();
        handler.warm_partition(2).await.unwrap();
        handler.warm_partition(3).await.unwrap();

        assert!(handler.owns_partition(1));
        assert!(handler.owns_partition(2));
        assert!(handler.owns_partition(3));

        handler.release_partition(2).await.unwrap();
        assert!(handler.owns_partition(1));
        assert!(!handler.owns_partition(2));
        assert!(handler.owns_partition(3));
    }
}
