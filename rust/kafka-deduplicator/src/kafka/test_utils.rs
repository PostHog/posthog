use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use async_trait::async_trait;

use super::rebalance_handler::RebalanceHandler;
use super::types::Partition;

use anyhow::Result;
use rdkafka::TopicPartitionList;

/// Test implementation of RebalanceHandler that tracks calls
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
    fn setup_assigned_partitions(&self, partitions: &TopicPartitionList) {
        self.assigned_count.fetch_add(1, Ordering::SeqCst);

        let mut assigned = self.assigned_partitions.lock().unwrap();
        for elem in partitions.elements() {
            assigned.push(Partition::from(elem));
        }
    }

    fn setup_revoked_partitions(&self, partitions: &TopicPartitionList) {
        self.revoked_count.fetch_add(1, Ordering::SeqCst);

        let mut revoked = self.revoked_partitions.lock().unwrap();
        for elem in partitions.elements() {
            revoked.push(Partition::from(elem));
        }
    }

    async fn async_setup_assigned_partitions(
        &self,
        _partitions: &TopicPartitionList,
    ) -> Result<()> {
        Ok(())
    }

    async fn cleanup_revoked_partitions(&self, _partitions: &TopicPartitionList) -> Result<()> {
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
