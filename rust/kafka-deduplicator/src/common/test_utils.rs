#[cfg(test)]
use crate::kafka::tracker::InFlightTracker;
#[cfg(test)]
use crate::kafka::types::{Partition, PartitionAssignment};

#[cfg(test)]
pub async fn assign_test_partitions(tracker: &InFlightTracker, topic: &str, partitions: Vec<i32>) {
    let assignments: Vec<PartitionAssignment> = partitions
        .into_iter()
        .map(|p| PartitionAssignment::new(Partition::new(topic.to_string(), p), Some(0)))
        .collect();
    tracker.mark_partitions_active(&assignments).await;
}
