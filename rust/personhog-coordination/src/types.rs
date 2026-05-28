use k8s_awareness::types::ControllerRef;
use serde::{Deserialize, Serialize};

/// A writer pod registered in etcd under `{prefix}pods/{pod_name}`.
///
/// Each writer pod creates this on startup with an etcd lease attached.
/// When the lease expires (pod crashes), the key is automatically deleted,
/// triggering the coordinator to reassign that pod's partitions.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegisteredPod {
    pub pod_name: String,
    /// Pod-template-hash (Deployment) or controller-revision-hash (StatefulSet).
    /// Populated via K8s awareness on registration. Empty when K8s awareness is disabled.
    #[serde(default)]
    pub generation: String,
    pub status: PodStatus,
    pub registered_at: i64,
    pub last_heartbeat: i64,
    /// The K8s controller (Deployment/StatefulSet) that owns this pod.
    /// Populated via K8s awareness on registration. None when K8s awareness is disabled.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub controller: Option<ControllerRef>,
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

/// Tracks the progress of moving a partition from one writer pod to another,
/// or a fresh initial assignment.
///
/// Stored under `{prefix}handoffs/{partition}`.
///
/// The coordinator creates the handoff (`Freezing`). If `old_owner` is
/// `Some` and that pod is alive, routers stash incoming traffic and the old
/// owner drains inflight. When the coordinator observes all freeze acks AND
/// (drained ack OR old_owner dead/missing), it advances to `Warming` so the
/// new owner can consume Kafka to a stable HWM. When the new owner acks
/// warming, the coordinator advances to `Complete`; routers drain stash to
/// the new owner and (if applicable) the old owner releases its cache.
///
/// `old_owner == None` is used for initial assignments where no prior owner
/// exists. The drain step is skipped automatically in that case.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HandoffState {
    pub partition: u32,
    /// Previous owner, if one existed. `None` indicates an initial
    /// assignment. The handoff skips the drain step when this is `None` or
    /// when the named pod is no longer active.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub old_owner: Option<String>,
    pub new_owner: String,
    pub phase: HandoffPhase,
    pub started_at: i64,
}

/// State machine for partition handoffs:
///
/// ```text
/// Freezing → Draining → Warming → Complete → (deleted)
///   ^routers   ^old owner  ^new owner    ^routers drain stash,
///    stash      drains      consumes to    old owner releases
///                inflight    stable HWM
/// ```
///
/// The phases are sequenced — routers stop *before* the old owner drains —
/// so that "no inflight" actually means "no producer can write more." If
/// routers and old owner transitioned in parallel, a slow router could
/// send a final request to the old owner after the old owner observed
/// inflight=0 momentarily and wrote its DrainedAck, advancing HWM past
/// the point warming snapshots.
///
/// Phase advancement:
///   - `Freezing → Draining`: every registered router has written a
///     `RouterFreezeAck`. From this point no router forwards new requests
///     to the old owner.
///   - `Draining → Warming`: the old owner has written a `PodDrainedAck`
///     (or it is no longer registered). From this point HWM is stable.
///   - `Warming → Complete`: the new owner has written a `PodWarmedAck`,
///     meaning its cache has been populated up to the stable HWM. The
///     phase write and the new `PartitionAssignment` happen atomically.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HandoffPhase {
    /// Routers are establishing per-partition stash queues. While in this
    /// phase, the old owner continues to serve writes — the gate that
    /// stops new traffic is each router's local `begin_stash`, not the
    /// old owner's behavior.
    Freezing,
    /// All routers have acked freeze, so no new requests can flow from
    /// any router to the old owner. The old owner now waits for its
    /// inflight handlers to complete and writes a `PodDrainedAck`.
    Draining,
    /// HWM is stable. New owner consumes Kafka from the writer's committed
    /// offset up to current HWM, populating cache.
    Warming,
    /// New owner is synced. Old owner should release; routers should drain
    /// stashed requests to the new owner and resume normal routing.
    Complete,
}

/// A router's acknowledgment that it has begun stashing traffic for a
/// partition. Stored under `{prefix}freeze_acks/{partition}/{router_name}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RouterFreezeAck {
    pub router_name: String,
    pub partition: u32,
    pub acked_at: i64,
}

/// The old owner's acknowledgment that all inflight request handlers for a
/// partition have completed. Because the leader's produce path awaits the
/// Kafka delivery future before returning success, "no inflight" implies
/// "every write this pod ever acked is durably in Kafka."
///
/// Stored under `{prefix}pod_drained_acks/{partition}/{pod_name}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PodDrainedAck {
    pub pod_name: String,
    pub partition: u32,
    pub acked_at: i64,
}

/// The new owner's acknowledgment that it has consumed Kafka up to the stable
/// HWM for the partition. Stored under
/// `{prefix}pod_warmed_acks/{partition}/{pod_name}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PodWarmedAck {
    pub pod_name: String,
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
            generation: String::new(),
            status: PodStatus::Ready,
            registered_at: 1700000000,
            last_heartbeat: 1700000010,
            controller: None,
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
            old_owner: Some("personhog-writer-1".to_string()),
            new_owner: "personhog-writer-3".to_string(),
            phase: HandoffPhase::Freezing,
            started_at: 1700000000,
        };
        let json = serde_json::to_string(&handoff).unwrap();
        let deserialized: HandoffState = serde_json::from_str(&json).unwrap();
        assert_eq!(handoff, deserialized);
    }

    #[test]
    fn handoff_state_initial_assignment_roundtrip() {
        let handoff = HandoffState {
            partition: 42,
            old_owner: None,
            new_owner: "personhog-writer-3".to_string(),
            phase: HandoffPhase::Freezing,
            started_at: 1700000000,
        };
        let json = serde_json::to_string(&handoff).unwrap();
        let deserialized: HandoffState = serde_json::from_str(&json).unwrap();
        assert_eq!(handoff, deserialized);
    }

    #[test]
    fn router_freeze_ack_roundtrip() {
        let ack = RouterFreezeAck {
            router_name: "router-0".to_string(),
            partition: 42,
            acked_at: 1700000000,
        };
        let json = serde_json::to_string(&ack).unwrap();
        let deserialized: RouterFreezeAck = serde_json::from_str(&json).unwrap();
        assert_eq!(ack, deserialized);
    }

    #[test]
    fn pod_drained_ack_roundtrip() {
        let ack = PodDrainedAck {
            pod_name: "leader-0".to_string(),
            partition: 42,
            acked_at: 1700000000,
        };
        let json = serde_json::to_string(&ack).unwrap();
        let deserialized: PodDrainedAck = serde_json::from_str(&json).unwrap();
        assert_eq!(ack, deserialized);
    }

    #[test]
    fn pod_warmed_ack_roundtrip() {
        let ack = PodWarmedAck {
            pod_name: "leader-1".to_string(),
            partition: 42,
            acked_at: 1700000000,
        };
        let json = serde_json::to_string(&ack).unwrap();
        let deserialized: PodWarmedAck = serde_json::from_str(&json).unwrap();
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
            (HandoffPhase::Freezing, "\"Freezing\""),
            (HandoffPhase::Warming, "\"Warming\""),
            (HandoffPhase::Complete, "\"Complete\""),
        ] {
            assert_eq!(serde_json::to_string(&phase).unwrap(), expected);
        }
    }
}
