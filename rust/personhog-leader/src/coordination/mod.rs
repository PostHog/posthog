use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use personhog_coordination::error::Result;
use personhog_coordination::pod::HandoffHandler;
use tracing::info;

use crate::cache::PartitionedCache;
use crate::inflight::InflightTracker;
use crate::warming::{warm_from_kafka, WarmingConfig};

const DRAIN_POLL_INTERVAL: Duration = Duration::from_millis(50);

/// Handles partition ownership lifecycle events for a leader pod.
///
/// Drives three phase responses via the `HandoffHandler` trait,
/// matching the four-phase handoff protocol
/// (`Freezing → Draining → Warming → Complete`):
///   - `drain_partition_inflight` (fired in `Draining` for the
///     old owner): waits until no in-flight request handlers remain
///     for the partition. By the time the coordinator advances to
///     `Draining`, every router has acked freeze and stopped
///     forwarding, so the inflight count strictly drops to zero.
///     Because the produce path awaits the Kafka delivery future
///     before returning, "no in-flight" implies "every write this
///     pod ever acked is durable in Kafka." The pod then writes
///     `PodDrainedAck` so the coordinator can advance to `Warming`.
///   - `warm_partition` (fired in `Warming` for the new owner):
///     consumes the `personhog_updates` topic for the partition and
///     repopulates the in-memory cache up to the now-stable HWM.
///   - `release_partition` (fired in `Complete` for the old owner):
///     drops the partition's cache after the routing table has
///     flipped to the new owner.
pub struct LeaderHandoffHandler {
    cache: Arc<PartitionedCache>,
    inflight: Arc<InflightTracker>,
    warming: WarmingConfig,
}

impl LeaderHandoffHandler {
    pub fn new(
        cache: Arc<PartitionedCache>,
        inflight: Arc<InflightTracker>,
        warming: WarmingConfig,
    ) -> Self {
        Self {
            cache,
            inflight,
            warming,
        }
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
        info!(partition, "warming partition cache from kafka");
        warm_from_kafka(&self.warming, &self.cache, partition).await?;
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
    use crate::warming::WarmingRetryPolicy;
    use common_kafka::config::KafkaConfig;

    /// `warm_partition` is exercised end-to-end in
    /// `tests/warming_integration.rs` against a mock Kafka cluster
    /// because it now consumes from a real broker. These unit tests
    /// cover the parts of `LeaderHandoffHandler` that don't require
    /// Kafka: drain semantics, release semantics, and `owns_partition`.
    fn handler() -> LeaderHandoffHandler {
        LeaderHandoffHandler::new(
            Arc::new(PartitionedCache::new(100)),
            Arc::new(InflightTracker::new()),
            WarmingConfig {
                kafka: KafkaConfig {
                    kafka_producer_linger_ms: 0,
                    kafka_producer_queue_mib: 50,
                    kafka_message_timeout_ms: 5000,
                    kafka_compression_codec: "none".to_string(),
                    kafka_hosts: "localhost:9092".to_string(),
                    kafka_tls: false,
                    kafka_producer_queue_messages: 1000,
                    kafka_client_rack: String::new(),
                    kafka_client_id: String::new(),
                    kafka_producer_batch_size: None,
                    kafka_producer_batch_num_messages: None,
                    kafka_producer_enable_idempotence: None,
                    kafka_producer_max_in_flight_requests_per_connection: None,
                    kafka_producer_topic_metadata_refresh_interval_ms: None,
                    kafka_producer_message_max_bytes: None,
                    kafka_producer_sticky_partitioning_linger_ms: None,
                },
                topic: "personhog_updates".to_string(),
                pod_name: "test".to_string(),
                writer_consumer_group: "personhog-writer".to_string(),
                lookback_offsets: 0,
                committed_offsets_timeout: Duration::from_secs(5),
                fetch_watermarks_timeout: Duration::from_secs(5),
                recv_timeout: Duration::from_secs(10),
                retry: WarmingRetryPolicy {
                    max_attempts: 3,
                    initial_backoff: Duration::from_millis(500),
                    max_backoff: Duration::from_secs(5),
                },
            },
        )
    }

    #[tokio::test]
    async fn release_partition_drops_cache_entry() {
        let handler = handler();
        // Simulate a successful prior warm by creating the partition
        // directly. We can't call `warm_partition` here because it
        // would try to talk to Kafka.
        handler.cache.create_partition(42);
        assert!(handler.owns_partition(42));

        handler.release_partition(42).await.unwrap();
        assert!(!handler.owns_partition(42));
    }

    #[tokio::test]
    async fn release_partition_is_idempotent_for_unknown_partition() {
        let handler = handler();
        // Releasing a partition that was never warmed must be a no-op,
        // not an error. The pod's watch loop can deliver Complete events
        // for partitions this pod never owned (e.g., during a rapid
        // assignment churn) and we shouldn't fail the protocol.
        handler.release_partition(99).await.unwrap();
        assert!(!handler.owns_partition(99));
    }

    #[tokio::test]
    async fn owns_partition_reflects_cache_state_across_lifecycle() {
        let handler = handler();
        assert!(!handler.owns_partition(1));
        handler.cache.create_partition(1);
        assert!(handler.owns_partition(1));
        handler.cache.create_partition(2);
        handler.cache.create_partition(3);
        assert!(handler.owns_partition(2));
        assert!(handler.owns_partition(3));

        handler.release_partition(2).await.unwrap();
        assert!(handler.owns_partition(1));
        assert!(!handler.owns_partition(2));
        assert!(handler.owns_partition(3));
    }

    #[tokio::test]
    async fn drain_partition_inflight_returns_immediately_when_empty() {
        let handler = handler();
        // No request handlers in flight → drain returns immediately.
        // The protocol relies on this for partitions that never
        // received traffic between Freezing and the actual drain call.
        handler.drain_partition_inflight(7).await.unwrap();
    }
}
