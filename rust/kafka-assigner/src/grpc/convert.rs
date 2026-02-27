use kafka_assigner_proto::kafka_assigner::v1 as proto;

use crate::types::{AssignmentEvent, PartitionAssignment, TopicPartition};

use proto::assignment_command::Command;

// ── Domain → Proto ──────────────────────────────────────────

impl From<&TopicPartition> for proto::TopicPartition {
    fn from(tp: &TopicPartition) -> Self {
        Self {
            topic: tp.topic.clone(),
            partition: tp.partition,
        }
    }
}

impl From<&AssignmentEvent> for proto::AssignmentCommand {
    fn from(event: &AssignmentEvent) -> Self {
        let command = match event {
            AssignmentEvent::Assignment {
                assigned,
                unassigned,
            } => Command::Assignment(proto::AssignmentUpdate {
                assigned: assigned.iter().map(proto::TopicPartition::from).collect(),
                unassigned: unassigned.iter().map(proto::TopicPartition::from).collect(),
            }),
            AssignmentEvent::Warm(handoff) => Command::Warm(proto::WarmPartition {
                partition: Some(proto::TopicPartition::from(&handoff.topic_partition())),
                current_owner: handoff.old_owner.clone(),
            }),
            AssignmentEvent::Release(handoff) => Command::Release(proto::ReleasePartition {
                partition: Some(proto::TopicPartition::from(&handoff.topic_partition())),
                new_owner: handoff.new_owner.clone(),
            }),
        };
        Self {
            command: Some(command),
        }
    }
}

// ── Proto → Domain ──────────────────────────────────────────

impl From<&proto::TopicPartition> for TopicPartition {
    fn from(tp: &proto::TopicPartition) -> Self {
        Self {
            topic: tp.topic.clone(),
            partition: tp.partition,
        }
    }
}

pub fn topic_partition_from_ready(req: &proto::PartitionReadyRequest) -> Option<TopicPartition> {
    req.partition.as_ref().map(TopicPartition::from)
}

pub fn topic_partition_from_released(
    req: &proto::PartitionReleasedRequest,
) -> Option<TopicPartition> {
    req.partition.as_ref().map(TopicPartition::from)
}

pub fn consumer_partitions(
    consumer: &str,
    assignments: &[PartitionAssignment],
) -> Vec<TopicPartition> {
    assignments
        .iter()
        .filter(|a| a.owner == consumer)
        .map(|a| a.topic_partition())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::HandoffPhase;
    use crate::types::HandoffState;

    #[test]
    fn topic_partition_roundtrip() {
        let domain = TopicPartition {
            topic: "events".to_string(),
            partition: 42,
        };
        let proto_tp = proto::TopicPartition::from(&domain);
        let back = TopicPartition::from(&proto_tp);
        assert_eq!(domain, back);
    }

    #[test]
    fn assignment_event_converts() {
        let event = AssignmentEvent::Assignment {
            assigned: vec![
                TopicPartition {
                    topic: "events".to_string(),
                    partition: 0,
                },
                TopicPartition {
                    topic: "events".to_string(),
                    partition: 1,
                },
            ],
            unassigned: vec![TopicPartition {
                topic: "clicks".to_string(),
                partition: 3,
            }],
        };
        let cmd = proto::AssignmentCommand::from(&event);
        match cmd.command {
            Some(Command::Assignment(update)) => {
                assert_eq!(update.assigned.len(), 2);
                assert_eq!(update.assigned[0].topic, "events");
                assert_eq!(update.assigned[0].partition, 0);
                assert_eq!(update.assigned[1].partition, 1);
                assert_eq!(update.unassigned.len(), 1);
                assert_eq!(update.unassigned[0].topic, "clicks");
                assert_eq!(update.unassigned[0].partition, 3);
            }
            _ => panic!("expected assignment command"),
        }
    }

    #[test]
    fn warm_event_includes_current_owner() {
        let event = AssignmentEvent::Warm(HandoffState {
            topic: "events".to_string(),
            partition: 5,
            old_owner: "c-0".to_string(),
            new_owner: "c-1".to_string(),
            phase: HandoffPhase::Warming,
            started_at: 0,
        });
        let cmd = proto::AssignmentCommand::from(&event);
        match cmd.command {
            Some(Command::Warm(warm)) => {
                let tp = warm.partition.unwrap();
                assert_eq!(tp.topic, "events");
                assert_eq!(tp.partition, 5);
                assert_eq!(warm.current_owner, "c-0");
            }
            _ => panic!("expected warm command"),
        }
    }

    #[test]
    fn release_event_includes_new_owner() {
        let event = AssignmentEvent::Release(HandoffState {
            topic: "events".to_string(),
            partition: 3,
            old_owner: "c-0".to_string(),
            new_owner: "c-1".to_string(),
            phase: HandoffPhase::Complete,
            started_at: 0,
        });
        let cmd = proto::AssignmentCommand::from(&event);
        match cmd.command {
            Some(Command::Release(rel)) => {
                let tp = rel.partition.unwrap();
                assert_eq!(tp.topic, "events");
                assert_eq!(tp.partition, 3);
                assert_eq!(rel.new_owner, "c-1");
            }
            _ => panic!("expected release command"),
        }
    }

    #[test]
    fn topic_partition_from_ready_extracts_tp() {
        let req = proto::PartitionReadyRequest {
            consumer_name: "c-0".to_string(),
            partition: Some(proto::TopicPartition {
                topic: "events".to_string(),
                partition: 7,
            }),
        };
        let tp = topic_partition_from_ready(&req).unwrap();
        assert_eq!(tp.topic, "events");
        assert_eq!(tp.partition, 7);
    }

    #[test]
    fn topic_partition_from_ready_returns_none_when_missing() {
        let req = proto::PartitionReadyRequest {
            consumer_name: "c-0".to_string(),
            partition: None,
        };
        assert!(topic_partition_from_ready(&req).is_none());
    }
}
