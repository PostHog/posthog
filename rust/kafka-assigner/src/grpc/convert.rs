use kafka_assigner_proto::kafka_assigner::v1 as proto;

use crate::types::{AssignmentEvent, HandoffState, PartitionAssignment, TopicPartition};

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

/// Convert a domain event into one or more proto commands.
///
/// `Assignment` produces a single command with all partitions.
/// `Warm` and `Release` are batched per-consumer at the domain level but
/// expand to one proto command per partition (the proto schema uses a single
/// partition per warm/release message).
pub fn to_proto_commands(event: &AssignmentEvent) -> Vec<proto::AssignmentCommand> {
    match event {
        AssignmentEvent::Assignment {
            assigned,
            unassigned,
        } => {
            vec![proto::AssignmentCommand {
                command: Some(Command::Assignment(proto::AssignmentUpdate {
                    assigned: assigned.iter().map(proto::TopicPartition::from).collect(),
                    unassigned: unassigned.iter().map(proto::TopicPartition::from).collect(),
                })),
            }]
        }
        AssignmentEvent::Warm(handoffs) => handoffs.iter().map(warm_command).collect(),
        AssignmentEvent::Release(handoffs) => handoffs.iter().map(release_command).collect(),
    }
}

fn warm_command(handoff: &HandoffState) -> proto::AssignmentCommand {
    proto::AssignmentCommand {
        command: Some(Command::Warm(proto::WarmPartition {
            partition: Some(proto::TopicPartition::from(&handoff.topic_partition())),
            current_owner: handoff.old_owner.clone(),
        })),
    }
}

fn release_command(handoff: &HandoffState) -> proto::AssignmentCommand {
    proto::AssignmentCommand {
        command: Some(Command::Release(proto::ReleasePartition {
            partition: Some(proto::TopicPartition::from(&handoff.topic_partition())),
            new_owner: handoff.new_owner.clone(),
        })),
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
        let cmds = to_proto_commands(&event);
        assert_eq!(cmds.len(), 1);
        match cmds[0].command {
            Some(Command::Assignment(ref update)) => {
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
    fn warm_batch_expands_to_individual_commands() {
        let event = AssignmentEvent::Warm(vec![
            HandoffState {
                topic: "events".to_string(),
                partition: 5,
                old_owner: "c-0".to_string(),
                new_owner: "c-1".to_string(),
                phase: HandoffPhase::Warming,
                started_at: 0,
            },
            HandoffState {
                topic: "events".to_string(),
                partition: 7,
                old_owner: "c-0".to_string(),
                new_owner: "c-1".to_string(),
                phase: HandoffPhase::Warming,
                started_at: 0,
            },
        ]);
        let cmds = to_proto_commands(&event);
        assert_eq!(cmds.len(), 2);

        match cmds[0].command {
            Some(Command::Warm(ref warm)) => {
                let tp = warm.partition.as_ref().unwrap();
                assert_eq!(tp.partition, 5);
                assert_eq!(warm.current_owner, "c-0");
            }
            _ => panic!("expected warm command"),
        }
        match cmds[1].command {
            Some(Command::Warm(ref warm)) => {
                let tp = warm.partition.as_ref().unwrap();
                assert_eq!(tp.partition, 7);
                assert_eq!(warm.current_owner, "c-0");
            }
            _ => panic!("expected warm command"),
        }
    }

    #[test]
    fn release_batch_expands_to_individual_commands() {
        let event = AssignmentEvent::Release(vec![HandoffState {
            topic: "events".to_string(),
            partition: 3,
            old_owner: "c-0".to_string(),
            new_owner: "c-1".to_string(),
            phase: HandoffPhase::Complete,
            started_at: 0,
        }]);
        let cmds = to_proto_commands(&event);
        assert_eq!(cmds.len(), 1);
        match cmds[0].command {
            Some(Command::Release(ref rel)) => {
                let tp = rel.partition.as_ref().unwrap();
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
