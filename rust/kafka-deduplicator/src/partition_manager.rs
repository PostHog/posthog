use dashmap::DashMap;

/// Unique identifier for a Kafka partition
pub type PartitionKey = (String, i32);

/// Tracks the safe commit offset per partition.
///
/// In a pipelined consumer, we consume batches ahead of processing.
/// This manager tracks what offset is safe to commit (i.e., fully processed).
pub struct PartitionManager {
    /// Safe commit offset per partition (topic, partition) -> offset
    safe_offsets: DashMap<PartitionKey, i64>,
}

impl Default for PartitionManager {
    fn default() -> Self {
        Self::new()
    }
}

impl PartitionManager {
    pub fn new() -> Self {
        Self {
            safe_offsets: DashMap::new(),
        }
    }

    /// Update the safe commit offset for a partition.
    /// Called after a batch has been fully processed.
    pub fn set_safe_offset(&self, topic: &str, partition: i32, offset: i64) {
        self.safe_offsets
            .insert((topic.to_string(), partition), offset);
    }

    /// Get the safe commit offset for a partition.
    /// Returns None if the partition hasn't been processed yet.
    pub fn get_safe_offset(&self, topic: &str, partition: i32) -> Option<i64> {
        self.safe_offsets
            .get(&(topic.to_string(), partition))
            .map(|r| *r)
    }

    /// Get all safe offsets for committing.
    pub fn get_all_safe_offsets(&self) -> Vec<(PartitionKey, i64)> {
        self.safe_offsets
            .iter()
            .map(|entry| (entry.key().clone(), *entry.value()))
            .collect()
    }

    /// Clear state for a partition (called on rebalance).
    pub fn clear_partition(&self, topic: &str, partition: i32) {
        self.safe_offsets.remove(&(topic.to_string(), partition));
    }

    /// Number of partitions being tracked.
    pub fn partition_count(&self) -> usize {
        self.safe_offsets.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_set_and_get_safe_offset() {
        let pm = PartitionManager::new();

        pm.set_safe_offset("topic", 0, 100);
        assert_eq!(pm.get_safe_offset("topic", 0), Some(100));

        pm.set_safe_offset("topic", 0, 200);
        assert_eq!(pm.get_safe_offset("topic", 0), Some(200));
    }

    #[test]
    fn test_multiple_partitions() {
        let pm = PartitionManager::new();

        pm.set_safe_offset("topic", 0, 100);
        pm.set_safe_offset("topic", 1, 200);
        pm.set_safe_offset("other-topic", 0, 50);

        assert_eq!(pm.get_safe_offset("topic", 0), Some(100));
        assert_eq!(pm.get_safe_offset("topic", 1), Some(200));
        assert_eq!(pm.get_safe_offset("other-topic", 0), Some(50));
        assert_eq!(pm.partition_count(), 3);
    }

    #[test]
    fn test_get_unknown_partition() {
        let pm = PartitionManager::new();
        assert_eq!(pm.get_safe_offset("topic", 0), None);
    }

    #[test]
    fn test_clear_partition() {
        let pm = PartitionManager::new();

        pm.set_safe_offset("topic", 0, 100);
        pm.set_safe_offset("topic", 1, 200);

        pm.clear_partition("topic", 0);

        assert_eq!(pm.get_safe_offset("topic", 0), None);
        assert_eq!(pm.get_safe_offset("topic", 1), Some(200));
        assert_eq!(pm.partition_count(), 1);
    }

    #[test]
    fn test_get_all_safe_offsets() {
        let pm = PartitionManager::new();

        pm.set_safe_offset("topic", 0, 100);
        pm.set_safe_offset("topic", 1, 200);

        let offsets = pm.get_all_safe_offsets();
        assert_eq!(offsets.len(), 2);

        let map: std::collections::HashMap<_, _> = offsets.into_iter().collect();
        assert_eq!(map.get(&("topic".to_string(), 0)), Some(&100));
        assert_eq!(map.get(&("topic".to_string(), 1)), Some(&200));
    }
}
