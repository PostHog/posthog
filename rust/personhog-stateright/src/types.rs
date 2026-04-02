use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

/// Partition ID (0-based index into Kafka partitions).
pub type Partition = u32;

/// Unique pod identifier (e.g., "pod-0", "pod-1").
pub type PodId = u8;

/// Unique router identifier (e.g., "router-0").
pub type RouterId = u8;

/// Lifecycle status of a pod as seen by the coordinator.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum PodStatus {
    Ready,
    Draining,
}

/// Phase of a partition handoff.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum HandoffPhase {
    Warming,
    Ready,
    Complete,
}

impl HandoffPhase {
    pub fn index(self) -> u8 {
        match self {
            Self::Warming => 0,
            Self::Ready => 1,
            Self::Complete => 2,
        }
    }
}

/// Tracks the progress of moving a partition from one pod to another.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct HandoffInfo {
    pub old_owner: PodId,
    pub new_owner: PodId,
    pub phase: HandoffPhase,
    /// Whether the old owner has released partition ownership.
    /// In EarlyRelease protocol this happens before Ready;
    /// in Current protocol this happens after Complete.
    pub old_owner_released: bool,
}

/// Which handoff protocol variant to model.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ProtocolVariant {
    /// Current code: old pod keeps ownership through Ready phase,
    /// releases only on Complete (after all routers acked).
    Current,
    /// Proposed fix: old pod drops ownership before Ready is signaled.
    EarlyRelease,
}

/// Configurable model parameters.
#[derive(Clone, Debug)]
pub struct ModelConfig {
    pub num_partitions: Partition,
    pub num_initial_pods: u8,
    pub num_scaling_pods: u8,
    pub num_routers: u8,
    pub allow_crashes: bool,
    pub protocol: ProtocolVariant,
}

impl ModelConfig {
    pub fn total_pods(&self) -> u8 {
        self.num_initial_pods + self.num_scaling_pods
    }

    pub fn initial_pod_ids(&self) -> Vec<PodId> {
        (0..self.num_initial_pods).collect()
    }

    pub fn scaling_pod_ids(&self) -> Vec<PodId> {
        (self.num_initial_pods..self.total_pods()).collect()
    }

    pub fn router_ids(&self) -> Vec<RouterId> {
        (0..self.num_routers).collect()
    }
}

/// The complete global state of the distributed system.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SystemState {
    // === etcd store (centralized, linearizable) ===
    /// Pods registered in etcd. Crashed pods are removed.
    pub registered_pods: BTreeMap<PodId, PodStatus>,
    /// Current partition-to-owner mapping (etcd assignments).
    pub assignments: BTreeMap<Partition, PodId>,
    /// Active handoffs (partition being moved).
    pub handoffs: BTreeMap<Partition, HandoffInfo>,
    /// Router cutover acks: (partition, router) pairs that have acked.
    pub acks: BTreeSet<(Partition, RouterId)>,

    // === Per-pod local state (may lag behind etcd) ===
    /// What each pod believes it owns (local `owned_partitions` set).
    pub pod_owned: BTreeMap<PodId, BTreeSet<Partition>>,

    // === Per-router local state (may lag behind etcd) ===
    /// Each router's local routing table.
    pub router_tables: BTreeMap<RouterId, BTreeMap<Partition, PodId>>,

    // === Request tracking (for invariant checking) ===
    /// Accepted writes: only writes where the target pod owns the partition.
    /// These are the writes actually being served.
    pub accepted_writes: BTreeSet<(Partition, PodId)>,

    /// Attempted writes: ALL writes routed by routers, including rejected ones.
    /// Used to check "writes_only_to_owners" invariant.
    pub attempted_writes: BTreeSet<(Partition, PodId)>,

    /// Whether the coordinator has seen a pod topology change that hasn't
    /// been processed yet (triggers rebalance).
    pub needs_rebalance: bool,
}

/// All possible actions in the model.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum Action {
    // --- Pod lifecycle ---
    PodJoin(PodId),
    PodCrash(PodId),
    PodStartDrain(PodId),

    // --- Coordinator actions ---
    CoordinatorRebalance,
    CoordinatorCompleteHandoff(Partition),
    CoordinatorCleanupStaleHandoff(Partition),

    // --- Pod handoff actions ---
    /// Old owner drops partition ownership (before Ready in EarlyRelease).
    OldPodReleasePartition(PodId, Partition),
    /// New owner warms cache and signals Ready.
    NewPodWarmAndSignalReady(PodId, Partition),
    /// Old owner does final cleanup after Complete phase.
    OldPodFinalCleanup(PodId, Partition),

    // --- Router actions ---
    /// Router executes cutover for a partition and writes ack.
    RouterExecuteCutover(RouterId, Partition),

    // --- Client requests ---
    /// Client sends a write request through a router for a partition.
    ClientWrite(RouterId, Partition),
    /// An active write completes (removed from tracking).
    ClientWriteComplete(Partition, PodId),
}

impl fmt::Display for Action {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PodJoin(p) => write!(f, "Pod{p}:Join"),
            Self::PodCrash(p) => write!(f, "Pod{p}:Crash"),
            Self::PodStartDrain(p) => write!(f, "Pod{p}:Drain"),
            Self::CoordinatorRebalance => write!(f, "Coord:Rebalance"),
            Self::CoordinatorCompleteHandoff(p) => write!(f, "Coord:Complete(P{p})"),
            Self::CoordinatorCleanupStaleHandoff(p) => write!(f, "Coord:CleanupStale(P{p})"),
            Self::OldPodReleasePartition(pod, part) => {
                write!(f, "Pod{pod}:Release(P{part})")
            }
            Self::NewPodWarmAndSignalReady(pod, part) => {
                write!(f, "Pod{pod}:WarmReady(P{part})")
            }
            Self::OldPodFinalCleanup(pod, part) => {
                write!(f, "Pod{pod}:Cleanup(P{part})")
            }
            Self::RouterExecuteCutover(r, part) => write!(f, "Router{r}:Cutover(P{part})"),
            Self::ClientWrite(r, part) => write!(f, "Client:Write(R{r},P{part})"),
            Self::ClientWriteComplete(part, pod) => {
                write!(f, "Client:WriteComplete(P{part},Pod{pod})")
            }
        }
    }
}
