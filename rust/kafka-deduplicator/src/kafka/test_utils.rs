use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;

use super::rebalance_handler::RebalanceHandler;
use super::stateful_context::StatefulConsumerContext;
use super::tracker::InFlightTracker;
use super::types::Partition;

use anyhow::Result;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::BaseConsumer;
use rdkafka::TopicPartitionList;

/// Test utilities for kafka module tests
pub fn create_test_consumer<H: RebalanceHandler + 'static>(
    handler: Arc<H>,
) -> BaseConsumer<StatefulConsumerContext> {
    let tracker = Arc::new(InFlightTracker::new());
    let context = StatefulConsumerContext::new(handler, tracker);

    let consumer: BaseConsumer<StatefulConsumerContext> = ClientConfig::new()
        .set("bootstrap.servers", "localhost:9092")
        .set("group.id", "test-group")
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .create_with_context(context)
        .expect("Consumer creation failed");

    consumer
}

// Test implementation of RebalanceHandler that tracks calls
#[derive(Default)]
pub struct TestRebalanceHandler {
    pub assigned_count: AtomicUsize,
    pub revoked_count: AtomicUsize,
    pub pre_rebalance_count: AtomicUsize,
    pub post_rebalance_count: AtomicUsize,
    pub assigned_partitions: Mutex<Vec<Partition>>,
    pub revoked_partitions: Mutex<Vec<Partition>>,
}

#[async_trait]
impl RebalanceHandler for TestRebalanceHandler {
    async fn on_partitions_assigned(&self, partitions: &TopicPartitionList) -> Result<()> {
        self.assigned_count.fetch_add(1, Ordering::SeqCst);

        let mut assigned = self.assigned_partitions.lock().unwrap();
        for elem in partitions.elements() {
            assigned.push(Partition::from(elem));
        }

        Ok(())
    }

    async fn on_partitions_revoked(&self, partitions: &TopicPartitionList) -> Result<()> {
        self.revoked_count.fetch_add(1, Ordering::SeqCst);

        let mut revoked = self.revoked_partitions.lock().unwrap();
        for elem in partitions.elements() {
            revoked.push(Partition::from(elem));
        }

        Ok(())
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        self.pre_rebalance_count.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        self.post_rebalance_count.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}
