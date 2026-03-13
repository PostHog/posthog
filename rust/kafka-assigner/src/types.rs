use serde::{Deserialize, Serialize};

/// A Kafka topic-partition pair — the fundamental unit of work assignment.
///
/// In Kafka, a partition is only meaningful in the context of a topic.
/// This type is used throughout the assigner to identify what's being assigned,
/// handed off, or watched.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TopicPartition {
    pub topic: String,
    pub partition: u32,
}

/// Configuration for a topic being coordinated within a consumer group.
///
/// Stored under `{prefix}config/topics/{topic}`. The coordinator uses this
/// to know how many partitions to distribute across consumers.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TopicConfig {
    pub topic: String,
    pub partition_count: u32,
}

/// A consumer registered in etcd under `{prefix}consumers/{consumer_name}`.
///
/// Each consumer creates this on startup with an etcd lease attached.
/// When the lease expires (consumer crashes), the key is automatically deleted,
/// triggering the coordinator to reassign that consumer's partitions.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegisteredConsumer {
    pub consumer_name: String,
    pub status: ConsumerStatus,
    pub registered_at: i64,
}

/// Lifecycle status of a consumer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConsumerStatus {
    /// Consumer is registered and eligible for partition assignments.
    Ready,
    /// Consumer is shutting down gracefully; excluded from new partition assignments.
    Draining,
}

/// Ownership of a single topic-partition, stored under
/// `{prefix}assignments/{topic}/{partition}`.
///
/// The consumer group is implicit in the prefix:
/// `prefix = /kafka-assigner/{consumer_group}/`
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PartitionAssignment {
    pub topic: String,
    pub partition: u32,
    /// The `consumer_name` that currently owns this topic-partition.
    pub owner: String,
    pub status: AssignmentStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AssignmentStatus {
    Active,
}

/// Tracks the progress of moving a topic-partition from one consumer to another.
/// Stored under `{prefix}handoffs/{topic}/{partition}`.
///
/// The coordinator creates the handoff (`Warming`), the new consumer advances it
/// to `Ready` after warming up, then the coordinator transitions to `Complete`
/// and updates the assignment atomically.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HandoffState {
    pub topic: String,
    pub partition: u32,
    pub old_owner: String,
    pub new_owner: String,
    pub phase: HandoffPhase,
    pub started_at: i64,
}

/// State machine for partition handoffs:
///
/// ```text
/// Warming → Ready → Complete → (deleted)
///   ^new consumer   ^coordinator    ^old consumer
///    warms           completes       releases
/// ```
///
/// Unlike personhog-coordination, there is no router ack step.
/// The coordinator transitions directly from `Ready` to `Complete`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HandoffPhase {
    /// New owner is warming up (e.g., downloading checkpoints, replaying logs).
    Warming,
    /// New owner finished warming. Coordinator will complete the handoff.
    Ready,
    /// Handoff complete. Assignment updated. Old owner should release resources.
    Complete,
}

/// A command the assigner sends to a consumer via gRPC.
///
/// This is the domain-level representation. It gets converted to the proto
/// `AssignmentCommand` at the gRPC boundary.
#[derive(Debug, Clone)]
pub enum AssignmentEvent {
    /// Batch assignment update: partitions added and/or removed.
    /// Also used for the initial snapshot on connect (assigned = current, unassigned = []).
    Assignment {
        assigned: Vec<TopicPartition>,
        unassigned: Vec<TopicPartition>,
    },
    /// Start warming a partition for handoff.
    Warm(HandoffState),
    /// Release a partition after handoff completion.
    Release(HandoffState),
}

impl PartitionAssignment {
    pub fn topic_partition(&self) -> TopicPartition {
        TopicPartition {
            topic: self.topic.clone(),
            partition: self.partition,
        }
    }
}

impl HandoffState {
    pub fn topic_partition(&self) -> TopicPartition {
        TopicPartition {
            topic: self.topic.clone(),
            partition: self.partition,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn topic_partition_roundtrip() {
        let tp = TopicPartition {
            topic: "events_json".to_string(),
            partition: 42,
        };
        let json = serde_json::to_string(&tp).unwrap();
        let deserialized: TopicPartition = serde_json::from_str(&json).unwrap();
        assert_eq!(tp, deserialized);
    }

    #[test]
    fn topic_config_roundtrip() {
        let config = TopicConfig {
            topic: "events_json".to_string(),
            partition_count: 1024,
        };
        let json = serde_json::to_string(&config).unwrap();
        let deserialized: TopicConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(config, deserialized);
    }

    #[test]
    fn registered_consumer_roundtrip() {
        let consumer = RegisteredConsumer {
            consumer_name: "consumer-0".to_string(),
            status: ConsumerStatus::Ready,
            registered_at: 1700000000,
        };
        let json = serde_json::to_string(&consumer).unwrap();
        let deserialized: RegisteredConsumer = serde_json::from_str(&json).unwrap();
        assert_eq!(consumer, deserialized);
    }

    #[test]
    fn partition_assignment_roundtrip() {
        let assignment = PartitionAssignment {
            topic: "events_json".to_string(),
            partition: 42,
            owner: "consumer-1".to_string(),
            status: AssignmentStatus::Active,
        };
        let json = serde_json::to_string(&assignment).unwrap();
        let deserialized: PartitionAssignment = serde_json::from_str(&json).unwrap();
        assert_eq!(assignment, deserialized);
    }

    #[test]
    fn partition_assignment_topic_partition() {
        let assignment = PartitionAssignment {
            topic: "events_json".to_string(),
            partition: 42,
            owner: "consumer-1".to_string(),
            status: AssignmentStatus::Active,
        };
        assert_eq!(
            assignment.topic_partition(),
            TopicPartition {
                topic: "events_json".to_string(),
                partition: 42,
            }
        );
    }

    #[test]
    fn handoff_state_roundtrip() {
        let handoff = HandoffState {
            topic: "events_json".to_string(),
            partition: 42,
            old_owner: "consumer-1".to_string(),
            new_owner: "consumer-3".to_string(),
            phase: HandoffPhase::Warming,
            started_at: 1700000000,
        };
        let json = serde_json::to_string(&handoff).unwrap();
        let deserialized: HandoffState = serde_json::from_str(&json).unwrap();
        assert_eq!(handoff, deserialized);
    }

    #[test]
    fn handoff_state_topic_partition() {
        let handoff = HandoffState {
            topic: "events_json".to_string(),
            partition: 42,
            old_owner: "consumer-1".to_string(),
            new_owner: "consumer-3".to_string(),
            phase: HandoffPhase::Warming,
            started_at: 1700000000,
        };
        assert_eq!(
            handoff.topic_partition(),
            TopicPartition {
                topic: "events_json".to_string(),
                partition: 42,
            }
        );
    }

    #[test]
    fn consumer_status_variants_serialize() {
        for (status, expected) in [
            (ConsumerStatus::Ready, "\"Ready\""),
            (ConsumerStatus::Draining, "\"Draining\""),
        ] {
            assert_eq!(serde_json::to_string(&status).unwrap(), expected);
        }
    }

    #[test]
    fn handoff_phase_variants_serialize() {
        for (phase, expected) in [
            (HandoffPhase::Warming, "\"Warming\""),
            (HandoffPhase::Ready, "\"Ready\""),
            (HandoffPhase::Complete, "\"Complete\""),
        ] {
            assert_eq!(serde_json::to_string(&phase).unwrap(), expected);
        }
    }

    #[test]
    fn topic_partition_eq_and_hash() {
        use std::collections::HashSet;

        let tp1 = TopicPartition {
            topic: "events".to_string(),
            partition: 0,
        };
        let tp2 = TopicPartition {
            topic: "events".to_string(),
            partition: 0,
        };
        let tp3 = TopicPartition {
            topic: "clicks".to_string(),
            partition: 0,
        };

        assert_eq!(tp1, tp2);
        assert_ne!(tp1, tp3);

        let mut set = HashSet::new();
        set.insert(tp1.clone());
        assert!(set.contains(&tp2));
        assert!(!set.contains(&tp3));
    }
}
