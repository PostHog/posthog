//! One cancellation token per partition assignment, founded at the first
//! delivery and cancelled at the revoke. A re-assignment founds a fresh
//! token, so work polled under the old assignment stays cancelled even
//! after this consumer owns the partition again: an ownership check would
//! pass it, and the new assignment replays its offsets.

use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::Mutex;

use common_kafka_consumer::{Partition, TopicPartition};
use tokio_util::sync::CancellationToken;

/// Equality ignores the token and compares the ledger generation, which
/// moves with every assignment, so a partition revoked and regained inside
/// one poll founds new groups for the regained offsets instead of joining
/// the cancelled ones.
#[derive(Clone, Debug)]
pub struct Assignment {
    pub partition: Partition,
    pub generation: u64,
    pub token: CancellationToken,
}

impl PartialEq for Assignment {
    fn eq(&self, other: &Self) -> bool {
        self.partition == other.partition && self.generation == other.generation
    }
}

impl Eq for Assignment {}

impl Hash for Assignment {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.partition.hash(state);
        self.generation.hash(state);
    }
}

#[derive(Default)]
pub struct PartitionAssignments {
    tokens: Mutex<HashMap<TopicPartition, CancellationToken>>,
}

impl PartitionAssignments {
    pub fn new() -> Self {
        Self::default()
    }

    /// Founded on first sight.
    pub fn token(&self, topic_partition: &TopicPartition) -> CancellationToken {
        self.tokens
            .lock()
            .unwrap()
            .entry(topic_partition.clone())
            .or_default()
            .clone()
    }

    /// Forgets the tokens too, so a re-assignment founds a fresh one.
    pub fn revoke(&self, partitions: &[(String, i32)]) {
        let mut tokens = self.tokens.lock().unwrap();
        for (topic, partition) in partitions {
            if let Some(token) = tokens.remove(&TopicPartition::new(topic, *partition)) {
                token.cancel();
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn revoke_cancels_the_current_token_and_founds_a_fresh_one_after() {
        let assignments = PartitionAssignments::new();
        let p0 = TopicPartition::new("test", 0);
        let first = assignments.token(&p0);
        assert!(!first.is_cancelled());
        assert!(!assignments.token(&p0).is_cancelled());

        assignments.revoke(&[("test".to_string(), 0)]);

        assert!(first.is_cancelled());
        let second = assignments.token(&p0);
        assert!(!second.is_cancelled(), "a re-assignment founds a new token");
        assert!(first.is_cancelled(), "the old assignment stays cancelled");
    }

    #[test]
    fn revoke_leaves_other_partitions_alone() {
        let assignments = PartitionAssignments::new();
        let p1 = assignments.token(&TopicPartition::new("test", 1));

        assignments.revoke(&[("test".to_string(), 0)]);

        assert!(!p1.is_cancelled());
    }
}
