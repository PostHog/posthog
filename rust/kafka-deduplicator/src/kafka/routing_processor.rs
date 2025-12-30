//! Routing Processor - Routes messages to partition workers via channels
//!
//! This processor groups incoming messages by partition and routes them
//! to dedicated partition workers, enabling true parallel processing with
//! pipelining between consumption and processing.

use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Result;
use axum::async_trait;
use futures::future::join_all;
use tracing::warn;

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_message::KafkaMessage;
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::partition_router::PartitionRouter;
use crate::kafka::types::Partition;

/// A processor that routes messages to partition-specific workers
///
/// This implements `BatchConsumerProcessor` so it can be used with the existing
/// `BatchConsumer`. Instead of processing messages directly, it groups them by
/// partition and sends them to dedicated workers via channels.
pub struct RoutingProcessor<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    router: Arc<PartitionRouter<T, P>>,
    offset_tracker: Arc<OffsetTracker>,
}

impl<T, P> RoutingProcessor<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    pub fn new(router: Arc<PartitionRouter<T, P>>, offset_tracker: Arc<OffsetTracker>) -> Self {
        Self {
            router,
            offset_tracker,
        }
    }

    /// Get a reference to the underlying router
    pub fn router(&self) -> &Arc<PartitionRouter<T, P>> {
        &self.router
    }

    /// Get a reference to the offset tracker
    pub fn offset_tracker(&self) -> &Arc<OffsetTracker> {
        &self.offset_tracker
    }
}

#[async_trait]
impl<T, P> BatchConsumerProcessor<T> for RoutingProcessor<T, P>
where
    T: Send + Sync + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    async fn process_batch(&self, messages: Vec<KafkaMessage<T>>) -> Result<()> {
        if messages.is_empty() {
            return Ok(());
        }

        // Group messages by partition
        let mut messages_by_partition: HashMap<Partition, Vec<KafkaMessage<T>>> = HashMap::new();

        for message in messages {
            let partition = message.get_topic_partition();
            messages_by_partition
                .entry(partition)
                .or_default()
                .push(message);
        }

        // Route all partitions concurrently to avoid head-of-line blocking
        // If one partition's channel is full (backpressure), it won't block other partitions
        let route_futures: Vec<_> = messages_by_partition
            .into_iter()
            .map(|(partition, partition_messages)| {
                let router = self.router.clone();
                // Assign a batch ID for ordering verification
                let batch_id = self.offset_tracker.assign_batch_id();

                async move {
                    let result = router
                        .route_batch(partition.clone(), partition_messages, batch_id)
                        .await;
                    (partition, result)
                }
            })
            .collect();

        let results = join_all(route_futures).await;

        // Log any failures but don't fail the batch - workers may have been removed during rebalance
        for (partition, result) in results {
            if let Err(e) = result {
                warn!(
                    "Failed to route batch to partition {}:{}: {}",
                    partition.topic(),
                    partition.partition_number(),
                    e
                );
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::partition_router::shutdown_workers;
    use crate::kafka::partition_router::PartitionRouterConfig;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tokio::time::{sleep, Duration};

    struct CountingProcessor {
        count: AtomicUsize,
    }

    impl CountingProcessor {
        fn new() -> Self {
            Self {
                count: AtomicUsize::new(0),
            }
        }

        fn get_count(&self) -> usize {
            self.count.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl BatchConsumerProcessor<String> for CountingProcessor {
        async fn process_batch(&self, messages: Vec<KafkaMessage<String>>) -> Result<()> {
            self.count.fetch_add(messages.len(), Ordering::SeqCst);
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_routing_processor_groups_by_partition() {
        let processor = Arc::new(CountingProcessor::new());
        let offset_tracker = Arc::new(OffsetTracker::new());
        let config = PartitionRouterConfig::default();
        let router = Arc::new(PartitionRouter::new(
            processor.clone(),
            offset_tracker.clone(),
            config,
        ));

        // Add workers for two partitions
        let p0 = Partition::new("test-topic".to_string(), 0);
        let p1 = Partition::new("test-topic".to_string(), 1);
        router.add_partition(p0.clone());
        router.add_partition(p1.clone());

        let routing_processor = RoutingProcessor::new(router.clone(), offset_tracker);

        // Create messages for different partitions
        let messages = vec![
            KafkaMessage::new_for_test(p0.clone(), 0, "msg1".to_string()),
            KafkaMessage::new_for_test(p0.clone(), 1, "msg2".to_string()),
            KafkaMessage::new_for_test(p1.clone(), 0, "msg3".to_string()),
        ];

        // Route the batch
        routing_processor.process_batch(messages).await.unwrap();

        // Give workers time to process
        sleep(Duration::from_millis(50)).await;

        // All 3 messages should have been processed
        assert_eq!(processor.get_count(), 3);

        // Cleanup
        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_routing_processor_handles_missing_worker() {
        let processor = Arc::new(CountingProcessor::new());
        let offset_tracker = Arc::new(OffsetTracker::new());
        let config = PartitionRouterConfig::default();
        let router = Arc::new(PartitionRouter::new(
            processor.clone(),
            offset_tracker.clone(),
            config,
        ));

        // Only add worker for partition 0
        let p0 = Partition::new("test-topic".to_string(), 0);
        router.add_partition(p0.clone());

        let routing_processor = RoutingProcessor::new(router.clone(), offset_tracker);

        // Create messages including one for a partition without a worker
        let p1 = Partition::new("test-topic".to_string(), 1);
        let messages = vec![
            KafkaMessage::new_for_test(p0.clone(), 0, "msg1".to_string()),
            KafkaMessage::new_for_test(p1, 0, "msg2".to_string()), // No worker for this
        ];

        // Should not fail, just warn
        let result = routing_processor.process_batch(messages).await;
        assert!(result.is_ok());

        // Give worker time to process
        sleep(Duration::from_millis(50)).await;

        // Only the message for partition 0 should be processed
        assert_eq!(processor.get_count(), 1);

        // Cleanup
        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }
}
