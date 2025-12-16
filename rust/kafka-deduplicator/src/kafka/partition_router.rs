//! Partition Router - Routes messages to partition-specific workers
//!
//! The router manages a collection of partition workers. Workers are created
//! synchronously during partition assignment (rebalance) and removed during
//! partition revocation. Message routing only sends to existing workers.

use std::collections::HashMap;
use std::sync::Arc;

use anyhow::{anyhow, Result};
use dashmap::DashMap;
use tracing::info;

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_message::KafkaMessage;
use crate::kafka::partition_worker::{PartitionBatch, PartitionWorker, PartitionWorkerConfig};
use crate::kafka::types::Partition;

/// Configuration for the partition router
#[derive(Debug, Clone, Default)]
pub struct PartitionRouterConfig {
    /// Configuration for individual partition workers
    pub worker_config: PartitionWorkerConfig,
}

/// Routes messages to partition-specific workers
///
/// Workers must be created via `add_partition` before messages can be routed.
/// This ensures workers are created synchronously during rebalance.
pub struct PartitionRouter<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    workers: DashMap<Partition, PartitionWorker<T>>,
    processor: Arc<P>,
    config: PartitionRouterConfig,
}

impl<T, P> PartitionRouter<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    /// Create a new partition router
    pub fn new(processor: Arc<P>, config: PartitionRouterConfig) -> Self {
        Self {
            workers: DashMap::new(),
            processor,
            config,
        }
    }

    /// Add a worker for a partition (called during partition assignment)
    ///
    /// This should be called synchronously during `on_partitions_assigned`.
    /// If a worker already exists for this partition, it will be reused (not replaced).
    /// This handles the rapid revoke→assign scenario where cleanup hasn't run yet.
    pub fn add_partition(&self, partition: Partition) {
        if self.workers.contains_key(&partition) {
            info!(
                "Worker already exists for {}:{}, reusing (rapid re-assignment)",
                partition.topic(),
                partition.partition_number()
            );
            return;
        }

        info!(
            "Creating partition worker for {}:{}",
            partition.topic(),
            partition.partition_number()
        );

        let worker = PartitionWorker::new(
            partition.clone(),
            self.processor.clone(),
            &self.config.worker_config,
        );
        self.workers.insert(partition, worker);
    }

    /// Add workers for multiple partitions
    pub fn add_partitions(&self, partitions: &[Partition]) {
        for partition in partitions {
            self.add_partition(partition.clone());
        }
    }

    /// Remove a worker for a partition (called during partition revocation)
    ///
    /// This should be called during `on_partitions_revoked`.
    /// Returns the worker for async shutdown if it existed.
    pub fn remove_partition(&self, partition: &Partition) -> Option<PartitionWorker<T>> {
        let worker = self.workers.remove(partition).map(|(_, w)| w);

        if worker.is_some() {
            info!(
                "Removed partition worker for {}:{}",
                partition.topic(),
                partition.partition_number()
            );
        }

        worker
    }

    /// Remove workers for multiple partitions
    /// Returns the workers for async shutdown
    pub fn remove_partitions(&self, partitions: &[Partition]) -> Vec<PartitionWorker<T>> {
        partitions
            .iter()
            .filter_map(|p| {
                let worker = self.workers.remove(p).map(|(_, w)| w);
                if worker.is_some() {
                    info!(
                        "Removed partition worker for {}:{}",
                        p.topic(),
                        p.partition_number()
                    );
                }
                worker
            })
            .collect()
    }

    /// Route a batch of messages to the appropriate partition worker
    ///
    /// Returns an error if no worker exists for the partition.
    pub async fn route_batch(
        &self,
        partition: Partition,
        messages: Vec<KafkaMessage<T>>,
    ) -> Result<()> {
        let batch = PartitionBatch::new(partition.clone(), messages);

        // Clone the sender and release the DashMap guard before awaiting.
        // This prevents blocking other partitions if this partition's channel
        // is full and backpressures.
        let sender = self
            .workers
            .get(&partition)
            .ok_or_else(|| {
                anyhow!(
                    "No worker for partition {}:{} - was it assigned?",
                    partition.topic(),
                    partition.partition_number()
                )
            })?
            .sender();
        // DashMap guard is now released

        sender.send(batch).await.map_err(|_| {
            anyhow!(
                "Failed to send batch to worker for {}:{}: channel closed",
                partition.topic(),
                partition.partition_number()
            )
        })
    }

    /// Route multiple batches organized by partition
    /// This is more efficient when routing messages from a single Kafka poll
    pub async fn route_batches(
        &self,
        batches: HashMap<Partition, Vec<KafkaMessage<T>>>,
    ) -> Result<()> {
        for (partition, messages) in batches {
            self.route_batch(partition, messages).await?;
        }
        Ok(())
    }

    /// Get the number of active workers
    pub fn worker_count(&self) -> usize {
        self.workers.len()
    }

    /// Get a list of active partitions
    pub fn active_partitions(&self) -> Vec<Partition> {
        self.workers.iter().map(|r| r.key().clone()).collect()
    }

    /// Check if a partition has an active worker
    pub fn has_partition(&self, partition: &Partition) -> bool {
        self.workers.contains_key(partition)
    }

    /// Shutdown all workers and return them for async cleanup
    pub fn shutdown_all(&self) -> Vec<PartitionWorker<T>> {
        let count = self.workers.len();
        info!("Shutting down partition router with {} workers", count);

        // Collect keys first, then remove each worker
        let keys: Vec<Partition> = self.workers.iter().map(|r| r.key().clone()).collect();
        let mut workers = Vec::with_capacity(keys.len());
        for key in keys {
            if let Some((_, worker)) = self.workers.remove(&key) {
                workers.push(worker);
            }
        }
        workers
    }
}

/// Helper function to shutdown workers asynchronously
pub async fn shutdown_workers<T: Send + 'static>(workers: Vec<PartitionWorker<T>>) {
    for worker in workers {
        worker.shutdown().await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::async_trait;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct TestProcessor {
        processed_count: AtomicUsize,
    }

    impl TestProcessor {
        fn new() -> Self {
            Self {
                processed_count: AtomicUsize::new(0),
            }
        }
    }

    #[async_trait]
    impl BatchConsumerProcessor<String> for TestProcessor {
        async fn process_batch(&self, messages: Vec<KafkaMessage<String>>) -> Result<()> {
            self.processed_count
                .fetch_add(messages.len(), Ordering::SeqCst);
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_router_add_partition() {
        let processor = Arc::new(TestProcessor::new());
        let config = PartitionRouterConfig::default();
        let router = PartitionRouter::new(processor, config);

        assert_eq!(router.worker_count(), 0);

        let partition = Partition::new("test-topic".to_string(), 0);
        router.add_partition(partition.clone());

        assert_eq!(router.worker_count(), 1);
        assert!(router.has_partition(&partition));

        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_router_route_requires_worker() {
        let processor = Arc::new(TestProcessor::new());
        let config = PartitionRouterConfig::default();
        let router = PartitionRouter::new(processor, config);

        let partition = Partition::new("test-topic".to_string(), 0);

        // Should fail - no worker exists
        let result = router.route_batch(partition.clone(), vec![]).await;
        assert!(result.is_err());

        // Add worker
        router.add_partition(partition.clone());

        // Should succeed now
        let result = router.route_batch(partition, vec![]).await;
        assert!(result.is_ok());

        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_router_multiple_partitions() {
        let processor = Arc::new(TestProcessor::new());
        let config = PartitionRouterConfig::default();
        let router = PartitionRouter::new(processor, config);

        let partitions: Vec<Partition> = (0..5)
            .map(|i| Partition::new("test-topic".to_string(), i))
            .collect();

        router.add_partitions(&partitions);
        assert_eq!(router.worker_count(), 5);

        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_router_remove_partition() {
        let processor = Arc::new(TestProcessor::new());
        let config = PartitionRouterConfig::default();
        let router = PartitionRouter::new(processor, config);

        let partition = Partition::new("test-topic".to_string(), 0);
        router.add_partition(partition.clone());

        assert_eq!(router.worker_count(), 1);

        let worker = router.remove_partition(&partition);
        assert!(worker.is_some());
        assert_eq!(router.worker_count(), 0);

        if let Some(w) = worker {
            w.shutdown().await;
        }
    }

    #[tokio::test]
    async fn test_router_reuses_after_readd() {
        let processor = Arc::new(TestProcessor::new());
        let config = PartitionRouterConfig::default();
        let router = PartitionRouter::new(processor, config);

        let partition = Partition::new("test-topic".to_string(), 0);

        // Add, remove, add again (simulating rebalance)
        router.add_partition(partition.clone());
        let worker = router.remove_partition(&partition);
        if let Some(w) = worker {
            w.shutdown().await;
        }

        router.add_partition(partition.clone());
        assert_eq!(router.worker_count(), 1);

        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_router_reuses_existing_worker_on_rapid_reassign() {
        // Simulates rapid revoke → assign where cleanup hasn't run yet
        // The router should reuse the existing worker instead of creating a new one
        let processor = Arc::new(TestProcessor::new());
        let config = PartitionRouterConfig::default();
        let router = PartitionRouter::new(processor, config);

        let partition = Partition::new("test-topic".to_string(), 0);

        // Initial assignment
        router.add_partition(partition.clone());
        assert_eq!(router.worker_count(), 1);

        // Rapid re-assignment (without remove - simulating cleanup not yet run)
        // This should reuse the existing worker
        router.add_partition(partition.clone());
        assert_eq!(router.worker_count(), 1);

        // Can still route messages
        let result = router.route_batch(partition.clone(), vec![]).await;
        assert!(result.is_ok());

        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_router_add_partition_idempotent() {
        // Calling add_partition multiple times should not create multiple workers
        let processor = Arc::new(TestProcessor::new());
        let config = PartitionRouterConfig::default();
        let router = PartitionRouter::new(processor, config);

        let partition = Partition::new("test-topic".to_string(), 0);

        // Add same partition 3 times
        router.add_partition(partition.clone());
        router.add_partition(partition.clone());
        router.add_partition(partition.clone());

        // Should still only have 1 worker
        assert_eq!(router.worker_count(), 1);

        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }
}
