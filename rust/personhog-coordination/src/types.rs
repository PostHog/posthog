use serde::{Deserialize, Serialize};

/// A writer pod registered in etcd under `{prefix}pods/{pod_name}`.
///
/// Each writer pod creates this on startup with an etcd lease attached.
/// When the lease expires (pod crashes), the key is automatically deleted,
/// triggering the coordinator to reassign that pod's partitions.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegisteredPod {
    pub pod_name: String,
    /// Placeholder for future blue/green deployments. Currently always "blue".
    pub generation: String,
    pub status: PodStatus,
    pub registered_at: i64,
    pub last_heartbeat: i64,
}

/// Lifecycle status of a writer pod.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PodStatus {
    /// Pod is registered and eligible for partition assignments.
    Ready,
    /// Pod is shutting down gracefully; excluded from new partition assignments.
    Draining,
}

/// A router registered in etcd under `{prefix}routers/{router_name}`.
///
/// Routers register with a lease so the coordinator knows how many routers
/// must acknowledge a cutover before a handoff can complete.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegisteredRouter {
    pub router_name: String,
    pub registered_at: i64,
    pub last_heartbeat: i64,
}

/// Ownership of a single Kafka partition, stored under `{prefix}assignments/{partition}`.
///
/// The routing table watches these keys to know which writer pod serves each partition.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PartitionAssignment {
    pub partition: u32,
    /// The `pod_name` of the writer pod that currently owns this partition.
    pub owner: String,
    pub status: AssignmentStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AssignmentStatus {
    Active,
}

/// Tracks the progress of moving a partition from one writer pod to another.
/// Stored under `{prefix}handoffs/{partition}`.
///
/// The coordinator creates the handoff (`Warming`), the new pod advances it
/// to `Ready`, routers perform the cutover and write acks, then the coordinator
/// transitions to `Complete` when all routers have acknowledged.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HandoffState {
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
///   ^new pod    ^routers cut over  ^old pod releases
///    warms       and ack
/// ```
///
/// The transition from `Ready` to `Complete` happens when every registered
/// router has written a `RouterCutoverAck` for this partition.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HandoffPhase {
    /// New owner is warming its cache (e.g. consuming from Kafka).
    Warming,
    /// New owner finished warming. Routers should cut over: stop sending to
    /// old pod, drain inflight, switch to new pod, then write an ack.
    Ready,
    /// All routers confirmed cutover. Old pod should release partition resources.
    Complete,
}

/// A router's acknowledgment that it has completed cutover for a partition.
/// Stored under `{prefix}handoff_acks/{partition}/{router_name}`.
///
/// Each router writes its own ack key (no contention between routers).
/// The coordinator counts acks against registered routers to decide when
/// to finalize the handoff.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RouterCutoverAck {
    pub router_name: String,
    pub partition: u32,
    pub acked_at: i64,
}

/// Written to `{prefix}coordinator/leader` by the coordinator that wins
/// the leader election. Other coordinators can read this to see who leads.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeaderInfo {
    pub holder: String,
    pub lease_id: i64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registered_pod_roundtrip() {
        let pod = RegisteredPod {
            pod_name: "personhog-writer-0".to_string(),
            generation: "blue".to_string(),
            status: PodStatus::Ready,
            registered_at: 1700000000,
            last_heartbeat: 1700000010,
        };
        let json = serde_json::to_string(&pod).unwrap();
        let deserialized: RegisteredPod = serde_json::from_str(&json).unwrap();
        assert_eq!(pod, deserialized);
    }

    #[test]
    fn registered_router_roundtrip() {
        let router = RegisteredRouter {
            router_name: "router-0".to_string(),
            registered_at: 1700000000,
            last_heartbeat: 1700000010,
        };
        let json = serde_json::to_string(&router).unwrap();
        let deserialized: RegisteredRouter = serde_json::from_str(&json).unwrap();
        assert_eq!(router, deserialized);
    }

    #[test]
    fn partition_assignment_roundtrip() {
        let assignment = PartitionAssignment {
            partition: 42,
            owner: "personhog-writer-1".to_string(),
            status: AssignmentStatus::Active,
        };
        let json = serde_json::to_string(&assignment).unwrap();
        let deserialized: PartitionAssignment = serde_json::from_str(&json).unwrap();
        assert_eq!(assignment, deserialized);
    }

    #[test]
    fn handoff_state_roundtrip() {
        let handoff = HandoffState {
            partition: 42,
            old_owner: "personhog-writer-1".to_string(),
            new_owner: "personhog-writer-3".to_string(),
            phase: HandoffPhase::Warming,
            started_at: 1700000000,
        };
        let json = serde_json::to_string(&handoff).unwrap();
        let deserialized: HandoffState = serde_json::from_str(&json).unwrap();
        assert_eq!(handoff, deserialized);
    }

    #[test]
    fn router_cutover_ack_roundtrip() {
        let ack = RouterCutoverAck {
            router_name: "router-0".to_string(),
            partition: 42,
            acked_at: 1700000000,
        };
        let json = serde_json::to_string(&ack).unwrap();
        let deserialized: RouterCutoverAck = serde_json::from_str(&json).unwrap();
        assert_eq!(ack, deserialized);
    }

    #[test]
    fn leader_info_roundtrip() {
        let leader = LeaderInfo {
            holder: "coordinator-0".to_string(),
            lease_id: 12345,
        };
        let json = serde_json::to_string(&leader).unwrap();
        let deserialized: LeaderInfo = serde_json::from_str(&json).unwrap();
        assert_eq!(leader, deserialized);
    }

    #[test]
    fn pod_status_variants_serialize() {
        for (status, expected) in [
            (PodStatus::Ready, "\"Ready\""),
            (PodStatus::Draining, "\"Draining\""),
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
}
