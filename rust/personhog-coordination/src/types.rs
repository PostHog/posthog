use std::collections::BTreeSet;

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
    /// `host:port` where this pod's gRPC server is reachable. Derived by
    /// the pod from its bind address (and POD_IP when binding a wildcard),
    /// so the advertised port is definitionally the serving port. Travels
    /// with ownership: the coordinator copies it into every handoff and
    /// assignment naming this pod, which is how routers learn where to
    /// dial without a second discovery system. `None` only for
    /// registrations written by binaries that predate the field.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub advertise_address: Option<String>,
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
    /// The owner's advertised `host:port`, copied from its registration
    /// via the handoff that installed it. Routers load it with the
    /// assignment so reachability arrives with ownership.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub advertise_address: Option<String>,
    pub status: AssignmentStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AssignmentStatus {
    Active,
}

/// What a rebalance plan asserts, at apply time, about a touched
/// partition's assignment record: the plan's handoffs derive their
/// `old_owner` from the assignments it read, so applying is only sound
/// while those records are exactly as read (moves) or still absent
/// (fresh partitions).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssignmentPrecondition {
    UnchangedSince { partition: u32, mod_revision: i64 },
    Absent { partition: u32 },
}

/// One cancellation-by-replacement in a plan application: the handoff
/// record at the partition's key is swapped — guarded on the
/// `mod_revision` the planner read — for the record that resolves its
/// stashes (a successor `Freezing` handoff, or a reaffirm `Complete`
/// toward the live current owner), with the predecessor's acks deleted
/// in the same transaction.
#[derive(Debug, Clone)]
pub struct HandoffReplacement {
    pub handoff: HandoffState,
    pub expected_mod_revision: i64,
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
    /// The new owner's advertised `host:port`, copied from its
    /// registration when the coordinator creates the handoff; lands in
    /// the assignment at Complete.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub new_owner_address: Option<String>,
    pub phase: HandoffPhase,
    pub started_at: i64,
    /// Unique identity of this handoff attempt. Acks echo it, and the
    /// coordinator's quorum checks only count acks whose id matches —
    /// without this, an ack written for a previous handoff of the same
    /// partition (e.g. re-put by a participant racing the coordinator's
    /// ack cleanup) could satisfy a later handoff's quorum and advance it
    /// past a drain or warm that never happened.
    #[serde(default)]
    pub handoff_id: String,
    /// The routers whose freeze acks this handoff requires: those
    /// registered when the coordinator created it, intersected with the
    /// live registry at evaluation (`required_freeze_ackers`), so the
    /// requirement only ever shrinks. Fixing membership at creation
    /// keeps the quorum satisfiable — every member's watch coverage
    /// spans this handoff's Freezing event, and a router that registers
    /// later is never required to ack an event it may not observe.
    ///
    /// Exempting late joiners is safe because the freeze quorum is an
    /// availability gate, not the safety boundary: a joining router
    /// opens stashes for in-flight handoffs before its routing table
    /// can forward anywhere, and the drain fence plus the broker's
    /// producer epoch reject anything that slips through before it is
    /// ever acked.
    ///
    /// `None` means the record predates this field; the quorum then
    /// falls back to requiring every live router. `Some([])` is a real
    /// snapshot — zero routers were registered at creation — and
    /// requires nobody.
    /// Carried by records written before the membership moved into its
    /// own key, and read for those. One current path still writes it: a
    /// reaffirm, which states an empty membership directly rather than
    /// minting a record no handoff would ever resolve. Nothing reads that
    /// value — a reaffirm is created at `Complete`, past every quorum
    /// check — but the field is written, so treat "absent" rather than
    /// "never written" as the thing this can be relied on for.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub freeze_quorum: Option<Vec<String>>,
    /// The id of the record holding this handoff's quorum membership,
    /// under `{prefix}freeze_quorums/{id}`. A plan's handoffs share one
    /// membership; inlined, it wrote the router fleet once per
    /// partition and exceeded etcd's request limit at fleet scale. An
    /// id that no longer resolves falls back to requiring every live
    /// router — the stricter answer, so a lost record can only delay a
    /// handoff, never advance one early.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub freeze_quorum_ref: Option<String>,
    /// Millisecond creation time. `started_at` (seconds) predates it and
    /// stays authoritative for the cancellation deadline — changing that
    /// field's units mid-roll would make old records' ages read as
    /// garbage — while this feeds the latency metrics, whose healthy
    /// values are sub-second and invisible at second resolution. Zero
    /// means the record predates the field; consumers skip rather than
    /// treat it as an epoch-zero time.
    #[serde(default)]
    pub created_at_ms: i64,
    /// When the handoff entered its current phase, stamped at creation
    /// and refreshed by the coordinator's CAS on every advance. Time
    /// spent per phase is measured from it directly — per-phase
    /// durations cannot be recovered from cumulative reached-times
    /// (differences of quantiles are not quantiles of differences).
    /// Zero means the record predates the field.
    #[serde(default)]
    pub phase_entered_at_ms: i64,
    /// A migration's hold: driver-owned, never advanced past Draining.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub held_by: Option<String>,
    /// Changelog epoch the record was planned under.
    #[serde(default)]
    pub config_epoch: u64,
}

impl HandoffState {
    pub fn is_held(&self) -> bool {
        self.held_by.is_some()
    }
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
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
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
    /// Echo of the handoff's `handoff_id`; the coordinator only counts
    /// this ack toward the handoff whose id it names.
    #[serde(default)]
    pub handoff_id: String,
    /// Millisecond stamp written by the store at put time, for span
    /// metrics (`acked_at` above keeps second resolution for protocol
    /// visibility). Zero in records written by earlier builds; span
    /// consumers skip zeros.
    #[serde(default)]
    pub acked_at_ms: i64,
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
    /// Echo of the handoff's `handoff_id`; the coordinator only counts
    /// this ack toward the handoff whose id it names.
    #[serde(default)]
    pub handoff_id: String,
    /// Millisecond stamp written by the store at put time, for span
    /// metrics (`acked_at` above keeps second resolution for protocol
    /// visibility). Zero in records written by earlier builds; span
    /// consumers skip zeros.
    #[serde(default)]
    pub acked_at_ms: i64,
}

/// The new owner's acknowledgment that it has consumed Kafka up to the stable
/// HWM for the partition. Stored under
/// `{prefix}pod_warmed_acks/{partition}/{pod_name}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PodWarmedAck {
    pub pod_name: String,
    pub partition: u32,
    pub acked_at: i64,
    /// Echo of the handoff's `handoff_id`; the coordinator only counts
    /// this ack toward the handoff whose id it names.
    #[serde(default)]
    pub handoff_id: String,
    /// Millisecond stamp written by the store at put time, for span
    /// metrics (`acked_at` above keeps second resolution for protocol
    /// visibility). Zero in records written by earlier builds; span
    /// consumers skip zeros.
    #[serde(default)]
    pub acked_at_ms: i64,
}

/// Written to `{prefix}coordinator/leader` by the coordinator that wins
/// the leader election. Other coordinators can read this to see who leads.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeaderInfo {
    pub holder: String,
    pub lease_id: i64,
}

/// The live changelog target under `{prefix}config/changelog`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangelogConfig {
    pub topic: String,
    pub partitions: u32,
    /// Monotonic from 1.
    pub epoch: u64,
    /// The writer's consumer group; a generation retires only once it has read it to the end.
    pub writer_group: String,
    /// Other consumer groups of the changelog, such as the relay's; a
    /// generation retires only once each of them has read it to the end too.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub retire_groups: Vec<String>,
    /// Generations some consumer may still be reading.
    pub draining: Vec<Generation>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Generation {
    pub topic: String,
    pub partitions: u32,
    pub epoch: u64,
}

impl ChangelogConfig {
    /// A freshly seeded config.
    pub fn new(topic: &str, partitions: u32) -> Self {
        Self {
            topic: topic.to_string(),
            partitions,
            epoch: 1,
            writer_group: String::new(),
            retire_groups: Vec::new(),
            draining: Vec::new(),
        }
    }

    /// Every consumer group a draining generation waits on before it retires.
    pub fn gated_groups(&self) -> impl Iterator<Item = &str> {
        std::iter::once(self.writer_group.as_str())
            .chain(self.retire_groups.iter().map(String::as_str))
    }

    pub fn target(&self) -> ChangelogTarget {
        ChangelogTarget {
            topic: self.topic.clone(),
            partitions: self.partitions,
        }
    }

    /// A flip raises the epoch. Within an epoch a retire shrinks `draining`, so
    /// a same-epoch object with more generations is an older one delivered
    /// late. A `retire_groups` edit also changes the object within an epoch
    /// and is never adopted from a watch; nothing reads that list from an
    /// adopted copy, since the coordinator and the control plane read etcd.
    pub fn supersedes(&self, adopted: &ChangelogConfig) -> bool {
        self.epoch > adopted.epoch
            || (self.epoch == adopted.epoch && self.draining.len() < adopted.draining.len())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangelogTarget {
    pub topic: String,
    pub partitions: u32,
}

/// Sealing is the point of no return: the old topic's ids are re-initialized there.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub enum MigrationPhase {
    Freezing,
    Draining,
    Sealing,
    Resuming,
    Complete,
    Cancelling,
    Cancelled,
}

impl MigrationPhase {
    pub fn may_transition_to(self, next: MigrationPhase) -> bool {
        matches!(
            (self, next),
            (Self::Freezing, Self::Draining)
                | (Self::Draining, Self::Sealing)
                | (Self::Sealing, Self::Resuming)
                | (Self::Resuming, Self::Complete)
                | (Self::Freezing | Self::Draining, Self::Cancelling)
                | (Self::Cancelling, Self::Cancelled)
        )
    }
}

/// A request to migrate: the control plane writes it, and the coordinator
/// starts the saga from it only once the fleet is quiet (`protocol::migration::fleet_quiet`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationRequest {
    pub id: String,
    pub from: ChangelogTarget,
    pub to: ChangelogTarget,
    pub requested_at_ms: i64,
    /// When the coordinator first saw it, on the coordinator's clock; the expiry counts from here.
    #[serde(default)]
    pub seen_at_ms: Option<i64>,
    /// Why the coordinator has not started it yet.
    #[serde(default)]
    pub waiting: Vec<String>,
}

impl MigrationRequest {
    /// The saga record the start creates; its pre-flip deadline counts from `now_ms`.
    pub fn start(&self, now_ms: i64) -> MigrationState {
        MigrationState {
            id: self.id.clone(),
            from: self.from.clone(),
            to: self.to.clone(),
            phase: MigrationPhase::Freezing,
            created_at_ms: now_ms,
            phase_entered_at_ms: now_ms,
            blocking: Vec::new(),
            cancel_reason: None,
        }
    }

    /// The history record of a request that never started.
    pub fn rejected(&self, reason: &str, now_ms: i64) -> MigrationState {
        MigrationState {
            phase: MigrationPhase::Cancelled,
            created_at_ms: self.requested_at_ms,
            phase_entered_at_ms: now_ms,
            blocking: std::iter::once(reason.to_string())
                .chain(self.waiting.iter().cloned())
                .collect(),
            ..self.start(self.requested_at_ms)
        }
    }
}

/// The saga record: only the coordinator creates and advances it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationState {
    pub id: String,
    pub from: ChangelogTarget,
    pub to: ChangelogTarget,
    pub phase: MigrationPhase,
    pub created_at_ms: i64,
    pub phase_entered_at_ms: i64,
    #[serde(default)]
    pub blocking: Vec<String>,
    /// Why the saga was cancelled, recorded by the cancelling write.
    pub cancel_reason: Option<String>,
}

/// A changelog consumer group's proof that it has read a draining generation
/// to its sealed end; retire waits for one from every group the config names.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DrainReport {
    pub topic: String,
    pub group: String,
    pub reported_by: String,
    pub reported_at_ms: i64,
}

/// One leader's report of the old partitions it sealed; the flip takes the union.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SealAck {
    pub migration_id: String,
    pub pod_name: String,
    pub sealed: BTreeSet<u32>,
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A record written before the snapshot and millisecond-timestamp
    /// fields existed must deserialize with the safe defaults: `None`
    /// quorum (fall back to all live routers) and zero clocks (metrics
    /// and the age gauge skip rather than measure from the epoch).
    /// Catches anyone removing a `serde(default)` during a refactor.
    #[test]
    fn pre_upgrade_handoff_record_deserializes_with_safe_defaults() {
        let legacy = r#"{
            "partition": 3,
            "old_owner": "p-old",
            "new_owner": "p-new",
            "phase": "Freezing",
            "started_at": 1700000000
        }"#;
        let h: HandoffState = serde_json::from_str(legacy).unwrap();
        assert_eq!(h.handoff_id, "");
        assert!(h.freeze_quorum.is_none());
        assert_eq!(h.created_at_ms, 0);
        assert_eq!(h.phase_entered_at_ms, 0);
        assert!(!h.is_held());
        assert_eq!(h.config_epoch, 0);
    }

    #[test]
    fn a_config_supersedes_by_epoch_then_by_retired_generations() {
        let generation = |epoch| Generation {
            topic: format!("g{epoch}"),
            partitions: 64,
            epoch,
        };
        let config = |epoch: u64, generations: &[u64]| ChangelogConfig {
            epoch,
            draining: generations.iter().map(|e| generation(*e)).collect(),
            ..ChangelogConfig::new("g", 128)
        };
        let adopted = config(3, &[2]);
        let cases = [
            ("a newer epoch", config(4, &[2, 3]), true),
            ("a retire at the same epoch", config(3, &[]), true),
            ("the same object", config(3, &[2]), false),
            (
                "the pre-retire object delivered late",
                config(3, &[1, 2]),
                false,
            ),
            ("an older epoch", config(2, &[]), false),
        ];
        for (name, candidate, expected) in cases {
            assert_eq!(candidate.supersedes(&adopted), expected, "{name}");
        }
    }

    #[test]
    fn registered_pod_roundtrip() {
        let pod = RegisteredPod {
            pod_name: "personhog-writer-0".to_string(),
            generation: String::new(),
            status: PodStatus::Ready,
            registered_at: 1700000000,
            last_heartbeat: 1700000010,
            controller: None,
            advertise_address: None,
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
            advertise_address: Some("10.1.2.3:50053".to_string()),
            status: AssignmentStatus::Active,
        };
        let json = serde_json::to_string(&assignment).unwrap();
        let deserialized: PartitionAssignment = serde_json::from_str(&json).unwrap();
        assert_eq!(assignment, deserialized);
    }

    /// Records written by binaries that predate advertise addresses must
    /// keep deserializing — the field arrives mid-rollout.
    #[test]
    fn pre_advertise_address_records_deserialize() {
        let assignment: PartitionAssignment = serde_json::from_str(
            r#"{"partition":1,"owner":"personhog-leader-0","status":"Active"}"#,
        )
        .unwrap();
        assert_eq!(assignment.advertise_address, None);
        let handoff: HandoffState = serde_json::from_str(
            r#"{"partition":1,"new_owner":"personhog-leader-0","phase":"Freezing","started_at":0}"#,
        )
        .unwrap();
        assert_eq!(handoff.new_owner_address, None);
    }

    #[test]
    fn handoff_state_roundtrip() {
        let handoff = HandoffState {
            partition: 42,
            old_owner: Some("personhog-writer-1".to_string()),
            new_owner: "personhog-writer-3".to_string(),
            phase: HandoffPhase::Freezing,
            started_at: 1700000000,
            handoff_id: "1700000000000-0".to_string(),
            freeze_quorum: None,
            freeze_quorum_ref: None,
            created_at_ms: 0,
            phase_entered_at_ms: 0,
            held_by: None,
            config_epoch: 0,
            new_owner_address: None,
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
            handoff_id: "1700000000000-0".to_string(),
            freeze_quorum: None,
            freeze_quorum_ref: None,
            created_at_ms: 0,
            phase_entered_at_ms: 0,
            held_by: None,
            config_epoch: 0,
            new_owner_address: None,
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
            acked_at_ms: 0,
            handoff_id: "1700000000000-0".to_string(),
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
            acked_at_ms: 0,
            handoff_id: "1700000000000-0".to_string(),
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
            acked_at_ms: 0,
            handoff_id: "1700000000000-0".to_string(),
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

    #[test]
    fn a_saga_cancels_only_before_the_seal() {
        use MigrationPhase::*;
        for phase in [
            Freezing, Draining, Sealing, Resuming, Complete, Cancelling, Cancelled,
        ] {
            assert_eq!(
                phase.may_transition_to(Cancelling),
                matches!(phase, Freezing | Draining),
                "{phase:?}"
            );
        }
    }
}
