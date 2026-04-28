use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use personhog_coordination::error::Result;
use personhog_coordination::pod::HandoffHandler;
use tracing::info;

use crate::cache::PartitionedCache;
use crate::inflight::InflightTracker;

const DRAIN_POLL_INTERVAL: Duration = Duration::from_millis(50);

/// Handles partition ownership lifecycle events for a leader pod.
///
/// Drives three phase responses via the `HandoffHandler` trait:
///   - `drain_partition_inflight`: waits until no in-flight request handlers
///     remain for the partition. Because the produce path awaits the Kafka
///     delivery future before returning, this implies every write this pod
///     ever acked is durable in Kafka.
///   - `warm_partition`: creates an empty per-partition cache slot. A
///     follow-up change wires this to consume the changelog topic and
///     repopulate state; until then, the new owner takes over with an empty
///     cache and falls back to PG on miss.
///   - `release_partition`: drops the partition's cache.
pub struct LeaderHandoffHandler {
    cache: Arc<PartitionedCache>,
    inflight: Arc<InflightTracker>,
}

impl LeaderHandoffHandler {
    pub fn new(cache: Arc<PartitionedCache>, inflight: Arc<InflightTracker>) -> Self {
        Self { cache, inflight }
    }

    pub fn owns_partition(&self, partition: u32) -> bool {
        self.cache.has_partition(partition)
    }
}

#[async_trait]
impl HandoffHandler for LeaderHandoffHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        info!(partition, "draining inflight handlers");
        self.inflight
            .wait_until_empty(partition, DRAIN_POLL_INTERVAL)
            .await;
        info!(partition, "inflight drained");
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        info!(partition, "warming partition cache");
        self.cache.create_partition(partition);
        info!(partition, "partition warmed");
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        info!(partition, "releasing partition");
        self.cache.drop_partition(partition);
        info!(partition, "partition released");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn handler() -> LeaderHandoffHandler {
        LeaderHandoffHandler::new(
            Arc::new(PartitionedCache::new(100)),
            Arc::new(InflightTracker::new()),
        )
    }

    #[tokio::test]
    async fn warm_partition_adds_ownership() {
        let handler = handler();
        assert!(!handler.owns_partition(42));
        handler.warm_partition(42).await.unwrap();
        assert!(handler.owns_partition(42));
    }

    #[tokio::test]
    async fn release_partition_removes_ownership() {
        let handler = handler();
        handler.warm_partition(42).await.unwrap();
        assert!(handler.owns_partition(42));
        handler.release_partition(42).await.unwrap();
        assert!(!handler.owns_partition(42));
    }

    #[tokio::test]
    async fn multiple_partitions() {
        let handler = handler();
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
