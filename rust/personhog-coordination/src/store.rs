use std::collections::HashMap;
use std::str::from_utf8;
use std::sync::{Arc, Mutex as StdMutex};

use assignment_coordination::store::EtcdStore;
use etcd_client::{Compare, CompareOp, DeleteOptions, PutOptions, Txn, TxnOp, WatchStream};

use crate::error::{Error, Result};
use crate::types::{
    AssignmentPrecondition, AssignmentStatus, HandoffReplacement, HandoffState, LeaderInfo,
    PartitionAssignment, PodDrainedAck, PodStatus, PodWarmedAck, RegisteredPod, RegisteredRouter,
    RouterFreezeAck,
};

/// All etcd key patterns used by the PersonHog store.
enum StoreKey<'a> {
    Pod(&'a str),
    PodsPrefix,
    Router(&'a str),
    RoutersPrefix,
    Assignment(u32),
    AssignmentsPrefix,
    Handoff(u32),
    HandoffsPrefix,
    // Freeze acks: each router writes one when it has begun stashing for a partition.
    FreezeAck { partition: u32, router: &'a str },
    FreezeAcksForPartition(u32),
    FreezeAcksPrefix,
    // Drained acks: the old owner writes one when all inflight handlers have completed.
    DrainedAck { partition: u32, pod: &'a str },
    DrainedAcksForPartition(u32),
    DrainedAcksPrefix,
    // Warmed acks: the new owner writes one after consuming Kafka up to the stable HWM.
    WarmedAck { partition: u32, pod: &'a str },
    WarmedAcksForPartition(u32),
    WarmedAcksPrefix,
    // Freeze quorum membership, shared by every handoff one plan creates.
    FreezeQuorum(&'a str),
    FreezeQuorumsPrefix,
    Leader,
    Generation,
    TotalPartitions,
}

impl StoreKey<'_> {
    fn resolve(&self, prefix: &str) -> String {
        match self {
            StoreKey::Pod(name) => format!("{prefix}pods/{name}"),
            StoreKey::PodsPrefix => format!("{prefix}pods/"),
            StoreKey::Router(name) => format!("{prefix}routers/{name}"),
            StoreKey::RoutersPrefix => format!("{prefix}routers/"),
            StoreKey::Assignment(p) => format!("{prefix}assignments/{p}"),
            StoreKey::AssignmentsPrefix => format!("{prefix}assignments/"),
            StoreKey::Handoff(p) => format!("{prefix}handoffs/{p}"),
            StoreKey::HandoffsPrefix => format!("{prefix}handoffs/"),
            StoreKey::FreezeAck { partition, router } => {
                format!("{prefix}freeze_acks/{partition}/{router}")
            }
            StoreKey::FreezeAcksForPartition(p) => format!("{prefix}freeze_acks/{p}/"),
            StoreKey::FreezeAcksPrefix => format!("{prefix}freeze_acks/"),
            StoreKey::DrainedAck { partition, pod } => {
                format!("{prefix}drained_acks/{partition}/{pod}")
            }
            StoreKey::DrainedAcksForPartition(p) => format!("{prefix}drained_acks/{p}/"),
            StoreKey::DrainedAcksPrefix => format!("{prefix}drained_acks/"),
            StoreKey::WarmedAck { partition, pod } => {
                format!("{prefix}warmed_acks/{partition}/{pod}")
            }
            StoreKey::WarmedAcksForPartition(p) => format!("{prefix}warmed_acks/{p}/"),
            StoreKey::WarmedAcksPrefix => format!("{prefix}warmed_acks/"),
            StoreKey::FreezeQuorum(id) => format!("{prefix}freeze_quorums/{id}"),
            StoreKey::FreezeQuorumsPrefix => format!("{prefix}freeze_quorums/"),
            StoreKey::Leader => format!("{prefix}coordinator/leader"),
            StoreKey::Generation => format!("{prefix}generation"),
            StoreKey::TotalPartitions => format!("{prefix}config/total_partitions"),
        }
    }
}

/// Domain-specific store for PersonHog coordination state.
///
/// Wraps the shared `EtcdStore` (generic JSON helpers, lease ops) and adds
/// PersonHog-specific key resolution and domain operations.
#[derive(Clone)]
pub struct PersonhogStore {
    inner: EtcdStore,
    /// Freeze-quorum memberships already read, by record id. An id
    /// names one immutable value (a chunked plan re-puts it only
    /// byte-identically), so a recorded membership cannot go stale; a
    /// plan's handoffs share one id, so this turns a few hundred reads
    /// per reconcile pass into one. Absence is never cached — the
    /// sweep can delete a record a later chunk re-creates.
    freeze_quorums: Arc<StdMutex<HashMap<String, Vec<String>>>>,
}

/// Counts store calls by the method that made them. The shared etcd
/// layer labels by primitive — `get`, `list_with_revision` — which is
/// too coarse to attribute load: a single `get` label covers the
/// coordinator's handoff read, a pod's convergence read, and every
/// other single-key lookup in the system.
pub(crate) fn count_call(site: &'static str) {
    metrics::counter!("personhog_coordination_store_calls_total", "site" => site).increment(1);
}

/// How a plan application ended, per partition.
#[derive(Debug, Default)]
pub struct PlanApplication {
    /// Partitions whose disposition landed.
    pub applied: Vec<u32>,
    /// Partitions whose guards failed — a record changed between the
    /// planner's read and the write; the next plan re-reads them.
    pub conflicted: Vec<u32>,
    /// Chunks the server refused as too large and that applied per
    /// unit instead: the configured budget exceeds the server's.
    pub over_budget_chunks: usize,
}

/// One partition's slice of a plan: the guards that make its
/// disposition safe and the ops that apply it. Chunking never splits a
/// unit, so a partition's disposition stays atomic across any split.
struct PlanUnit {
    partition: u32,
    guards: Vec<UnitGuard>,
    ops: Vec<UnitOp>,
    bytes: usize,
    references_quorum: bool,
}

enum UnitGuard {
    /// The key was never created (create_revision 0).
    Absent(String),
    /// The key's mod_revision is exactly this.
    ModRevision(String, i64),
}

impl UnitGuard {
    fn key(&self) -> &str {
        match self {
            UnitGuard::Absent(key) | UnitGuard::ModRevision(key, _) => key,
        }
    }
}

enum UnitOp {
    Put(String, Vec<u8>),
    DeletePrefix(String),
}

/// Whether etcd refused a transaction for its size — past
/// `--max-txn-ops` (`ErrGRPCTooManyOps`) or `--max-request-bytes`
/// (`ErrGRPCRequestTooLarge`). Matched on the message: the gRPC code
/// is a generic InvalidArgument.
fn is_txn_too_large(e: &Error) -> bool {
    matches!(
        e,
        Error::Store(assignment_coordination::error::Error::Etcd(
            etcd_client::Error::GRpcStatus(status)
        )) if status.message().contains("too many operations")
            || status.message().contains("request is too large")
    )
}

/// Greedy chunk boundaries over per-unit `(guards, ops)` costs: a chunk
/// takes units while its compare list and its op list both stay within
/// `budget` — etcd checks the two lists separately against
/// `--max-txn-ops`. `reserve_ops` holds back room in every chunk for
/// ops added on top of its units (the freeze-quorum write).
fn plan_chunk_ranges(
    costs: &[(usize, usize)],
    budget: usize,
    reserve_ops: usize,
) -> Vec<std::ops::Range<usize>> {
    let budget = budget.max(1);
    let mut ranges = Vec::new();
    let mut start = 0;
    let (mut guards, mut ops) = (0, 0);
    for (i, &(g, o)) in costs.iter().enumerate() {
        let fits = guards + g <= budget && ops + o + reserve_ops <= budget;
        // A chunk always takes at least one unit, so a budget below a
        // single unit's cost still makes progress and lets the server
        // be the judge.
        if i > start && !fits {
            ranges.push(start..i);
            start = i;
            guards = 0;
            ops = 0;
        }
        guards += g;
        ops += o;
    }
    if start < costs.len() {
        ranges.push(start..costs.len());
    }
    ranges
}

impl PersonhogStore {
    pub fn new(inner: EtcdStore) -> Self {
        Self {
            inner,
            freeze_quorums: Arc::new(StdMutex::new(HashMap::new())),
        }
    }

    pub fn inner(&self) -> &EtcdStore {
        &self.inner
    }

    fn key(&self, k: StoreKey<'_>) -> String {
        k.resolve(self.inner.prefix())
    }

    // ── Pod operations ──────────────────────────────────────────

    pub async fn register_pod(&self, pod: &RegisteredPod, lease_id: i64) -> Result<()> {
        count_call("register_pod");
        let key = self.key(StoreKey::Pod(&pod.pod_name));
        Ok(self.inner.put(&key, pod, Some(lease_id)).await?)
    }

    /// The exact key `register_pod` writes for a pod, for watchers that
    /// must match their own registration and nothing else under the
    /// prefix.
    pub fn pod_registration_key(&self, pod_name: &str) -> String {
        self.key(StoreKey::Pod(pod_name))
    }

    pub async fn get_pod(&self, pod_name: &str) -> Result<Option<RegisteredPod>> {
        count_call("get_pod");
        let key = self.key(StoreKey::Pod(pod_name));
        Ok(self.inner.get(&key).await?)
    }

    /// Bypasses the protocol: see the crate's `test-support` feature.
    #[cfg(any(test, feature = "test-support"))]
    pub async fn delete_pod(&self, pod_name: &str) -> Result<()> {
        let key = self.key(StoreKey::Pod(pod_name));
        Ok(self.inner.delete(&key).await?)
    }

    pub async fn list_pods(&self) -> Result<Vec<RegisteredPod>> {
        count_call("list_pods");
        let key = self.key(StoreKey::PodsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    /// List pods along with the etcd revision of the snapshot, so a watch
    /// can be anchored strictly after it.
    pub async fn list_pods_with_revision(&self) -> Result<(Vec<RegisteredPod>, i64)> {
        count_call("list_pods_with_revision");
        let key = self.key(StoreKey::PodsPrefix);
        Ok(self.inner.list_with_revision(&key).await?)
    }

    pub async fn update_pod_status(
        &self,
        pod_name: &str,
        status: PodStatus,
        lease_id: i64,
    ) -> Result<()> {
        count_call("update_pod_status");
        let key = self.key(StoreKey::Pod(pod_name));
        let mut pod: RegisteredPod = self
            .inner
            .get(&key)
            .await?
            .ok_or_else(|| Error::NotFound(format!("pod {pod_name}")))?;
        pod.status = status;
        Ok(self.inner.put(&key, &pod, Some(lease_id)).await?)
    }

    pub async fn watch_pods(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::PodsPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    /// Watch pod registrations from an explicit revision (inclusive),
    /// replaying events since that revision even if they predate the
    /// watch's creation.
    pub async fn watch_pods_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_pods_from");
        let key = self.key(StoreKey::PodsPrefix);
        Ok(self.inner.watch_from(&key, start_revision).await?)
    }

    /// The current etcd store revision, for anchoring watches.
    pub async fn current_revision(&self) -> Result<i64> {
        count_call("current_revision");
        Ok(self.inner.current_revision().await?)
    }

    // ── Router operations ────────────────────────────────────────

    pub async fn register_router(&self, router: &RegisteredRouter, lease_id: i64) -> Result<()> {
        count_call("register_router");
        let key = self.key(StoreKey::Router(&router.router_name));
        Ok(self.inner.put(&key, router, Some(lease_id)).await?)
    }

    pub async fn list_routers(&self) -> Result<Vec<RegisteredRouter>> {
        count_call("list_routers");
        let key = self.key(StoreKey::RoutersPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn watch_routers(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::RoutersPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    pub async fn watch_routers_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_routers_from");
        let key = self.key(StoreKey::RoutersPrefix);
        Ok(self.inner.watch_from(&key, start_revision).await?)
    }

    // ── Assignment operations ───────────────────────────────────

    pub async fn get_assignment(&self, partition: u32) -> Result<Option<PartitionAssignment>> {
        count_call("get_assignment");
        let key = self.key(StoreKey::Assignment(partition));
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_assignments(&self) -> Result<Vec<PartitionAssignment>> {
        count_call("list_assignments");
        let key = self.key(StoreKey::AssignmentsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    /// Like `list_assignments`, but also returns the etcd revision of the
    /// snapshot, for gap-free snapshot-then-watch handshakes.
    pub async fn list_assignments_with_revision(&self) -> Result<(Vec<PartitionAssignment>, i64)> {
        count_call("list_assignments_with_revision");
        let key = self.key(StoreKey::AssignmentsPrefix);
        Ok(self.inner.list_with_revision(&key).await?)
    }

    /// Like `list_assignments`, but pairs each record with its key's
    /// `mod_revision` so a plan can assert, at apply time, that the
    /// assignments it read are unchanged (`AssignmentPrecondition`).
    pub async fn list_assignments_with_mod_revisions(
        &self,
    ) -> Result<Vec<(PartitionAssignment, i64)>> {
        count_call("list_assignments_with_mod_revisions");
        let key = self.key(StoreKey::AssignmentsPrefix);
        Ok(self.inner.list_with_mod_revisions(&key).await?)
    }

    /// Bypasses the protocol: see the crate's `test-support` feature.
    #[cfg(any(test, feature = "test-support"))]
    pub async fn put_assignments(&self, assignments: &[PartitionAssignment]) -> Result<()> {
        if assignments.is_empty() {
            return Ok(());
        }
        let ops: Vec<TxnOp> = assignments
            .iter()
            .map(|a| {
                let key = self.key(StoreKey::Assignment(a.partition));
                let value = serde_json::to_vec(a)?;
                Ok(TxnOp::put(key, value, None))
            })
            .collect::<Result<Vec<_>>>()?;
        let txn = Txn::new().and_then(ops);
        self.inner.txn(txn).await?;
        Ok(())
    }

    // ── Handoff operations ──────────────────────────────────────

    pub async fn get_handoff(&self, partition: u32) -> Result<Option<HandoffState>> {
        count_call("get_handoff");
        let key = self.key(StoreKey::Handoff(partition));
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_handoffs(&self) -> Result<Vec<HandoffState>> {
        count_call("list_handoffs");
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    /// Like `list_handoffs`, but also returns the etcd revision of the
    /// snapshot. Pair with `watch_handoffs_from(revision + 1)` for a
    /// gap-free snapshot-then-watch handshake.
    pub async fn list_handoffs_with_revision(&self) -> Result<(Vec<HandoffState>, i64)> {
        count_call("list_handoffs_with_revision");
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.list_with_revision(&key).await?)
    }

    /// Like `list_handoffs`, but pairs each record with its key's
    /// `mod_revision`, so a later replacement can be guarded on the
    /// record being exactly the one this snapshot read.
    pub async fn list_handoffs_with_mod_revisions(&self) -> Result<Vec<(HandoffState, i64)>> {
        count_call("list_handoffs_with_mod_revisions");
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.list_with_mod_revisions(&key).await?)
    }

    /// Bypasses the protocol: see the crate's `test-support` feature.
    #[cfg(any(test, feature = "test-support"))]
    pub async fn put_handoff(&self, handoff: &HandoffState) -> Result<()> {
        count_call("put_handoff");
        let key = self.key(StoreKey::Handoff(handoff.partition));
        Ok(self.inner.put(&key, handoff, None).await?)
    }

    /// Compare-and-swap a handoff's phase. Reads the current handoff,
    /// verifies its phase matches `expected`, and writes a copy with
    /// `new_phase` only if the etcd key's mod_revision hasn't changed —
    /// mod_revision rather than version, so the guard can never match a
    /// different incarnation of the key after a delete-and-recreate.
    ///
    /// Returns `Ok(true)` if the swap succeeded, `Ok(false)` if the handoff
    /// was concurrently modified or its phase no longer matches `expected`.
    /// Used by `check_phase_advance` to avoid duplicate phase writes when
    /// multiple watch loops fire `check_phase_advance` concurrently for the
    /// same partition.
    /// `expected_id` names the handoff attempt the caller validated. The
    /// key can be replaced between that validation and this write —
    /// cancellation swaps in a successor and deletes the old acks in one
    /// transaction — and a `mod_revision` guard taken on a re-read here
    /// would not notice, because it only proves nothing changed since
    /// *this* function looked.
    pub async fn cas_handoff_phase(
        &self,
        partition: u32,
        expected_id: &str,
        expected: crate::types::HandoffPhase,
        new_phase: crate::types::HandoffPhase,
    ) -> Result<bool> {
        count_call("cas_handoff_phase");
        let handoff_key = self.key(StoreKey::Handoff(partition));
        let Some((mut handoff, mod_revision)) = self
            .inner
            .get_with_mod_revision::<HandoffState>(&handoff_key)
            .await?
        else {
            return Ok(false);
        };
        if handoff.phase != expected || handoff.handoff_id != expected_id {
            return Ok(false);
        }
        handoff.phase = new_phase;
        // The phase clock restarts with the phase: duration metrics and
        // the per-phase age gauge read this stamp.
        handoff.phase_entered_at_ms = assignment_coordination::util::now_millis();
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                handoff_key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![TxnOp::put(
                handoff_key,
                serde_json::to_vec(&handoff)?,
                None,
            )]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    /// Read a handoff along with its etcd mod_revision, for use with
    /// `delete_handoff_and_acks_if_unchanged`.
    pub async fn get_handoff_with_mod_revision(
        &self,
        partition: u32,
    ) -> Result<Option<(HandoffState, i64)>> {
        count_call("get_handoff_with_mod_revision");
        let key = self.key(StoreKey::Handoff(partition));
        Ok(self.inner.get_with_mod_revision(&key).await?)
    }

    /// Atomically delete a handoff record and every ack written for its
    /// partition — but only if the record's mod_revision still matches
    /// `expected_mod_revision`. Cleanup decisions are made against snapshot
    /// reads that can race a concurrent delete-and-recreate at the same
    /// key (cancellation followed by an immediate rebalance); an unguarded
    /// delete pair would destroy the healthy successor handoff and its
    /// acks. Returns whether the delete happened.
    pub async fn delete_handoff_and_acks_if_unchanged(
        &self,
        partition: u32,
        expected_mod_revision: i64,
    ) -> Result<bool> {
        count_call("delete_handoff_and_acks_if_unchanged");
        let handoff_key = self.key(StoreKey::Handoff(partition));
        let prefix_delete = || Some(DeleteOptions::new().with_prefix());
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                handoff_key.clone(),
                CompareOp::Equal,
                expected_mod_revision,
            )])
            .and_then(vec![
                TxnOp::delete(
                    self.key(StoreKey::FreezeAcksForPartition(partition)),
                    prefix_delete(),
                ),
                TxnOp::delete(
                    self.key(StoreKey::DrainedAcksForPartition(partition)),
                    prefix_delete(),
                ),
                TxnOp::delete(
                    self.key(StoreKey::WarmedAcksForPartition(partition)),
                    prefix_delete(),
                ),
                TxnOp::delete(handoff_key, None),
            ]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    /// Bypasses the protocol: see the crate's `test-support` feature.
    #[cfg(any(test, feature = "test-support"))]
    pub async fn delete_handoff(&self, partition: u32) -> Result<()> {
        let key = self.key(StoreKey::Handoff(partition));
        Ok(self.inner.delete(&key).await?)
    }

    pub async fn watch_handoffs(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    /// Watch handoffs from an explicit revision (inclusive), replaying
    /// events since that revision even if they predate the watch's
    /// creation.
    pub async fn watch_handoffs_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_handoffs_from");
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.watch_from(&key, start_revision).await?)
    }

    // ── Freeze ack operations (router -> coordinator) ────────────

    pub async fn put_freeze_ack(&self, ack: &RouterFreezeAck) -> Result<()> {
        count_call("put_freeze_ack");
        let key = self.key(StoreKey::FreezeAck {
            partition: ack.partition,
            router: &ack.router_name,
        });
        // The store stamps the millisecond clock so span metrics never
        // depend on each writer remembering to.
        let mut stamped = ack.clone();
        stamped.acked_at_ms = assignment_coordination::util::now_millis();
        Ok(self.inner.put(&key, &stamped, None).await?)
    }

    /// One transaction per chunk of acks in place of one round trip per
    /// ack: a plan freezing hundreds of partitions has every router
    /// acking each of them, and serial puts hold the freeze quorum on
    /// the slowest router's whole sequence. `max_txn_ops` must not
    /// exceed the server's own limit, which refuses a larger batch
    /// outright. An empty batch costs nothing.
    pub async fn put_freeze_acks(
        &self,
        acks: &[RouterFreezeAck],
        max_txn_ops: usize,
    ) -> Result<()> {
        for chunk in acks.chunks(max_txn_ops.max(1)) {
            count_call("put_freeze_acks");
            let mut ops = Vec::with_capacity(chunk.len());
            for ack in chunk {
                let key = self.key(StoreKey::FreezeAck {
                    partition: ack.partition,
                    router: &ack.router_name,
                });
                // The store stamps the millisecond clock so span metrics
                // never depend on each writer remembering to.
                let mut stamped = ack.clone();
                stamped.acked_at_ms = assignment_coordination::util::now_millis();
                ops.push(TxnOp::put(key, serde_json::to_vec(&stamped)?, None));
            }
            metrics::counter!("personhog_coordination_freeze_acks_written_total")
                .increment(chunk.len() as u64);
            self.inner.txn(Txn::new().and_then(ops)).await?;
        }
        Ok(())
    }

    pub async fn list_freeze_acks(&self, partition: u32) -> Result<Vec<RouterFreezeAck>> {
        count_call("list_freeze_acks");
        let key = self.key(StoreKey::FreezeAcksForPartition(partition));
        Ok(self.inner.list(&key).await?)
    }

    pub async fn delete_freeze_acks(&self, partition: u32) -> Result<()> {
        let key = self.key(StoreKey::FreezeAcksForPartition(partition));
        Ok(self.inner.delete_prefix(&key).await?)
    }

    pub async fn watch_freeze_acks(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::FreezeAcksPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    pub async fn watch_freeze_acks_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_freeze_acks_from");
        let key = self.key(StoreKey::FreezeAcksPrefix);
        Ok(self.inner.watch_from(&key, start_revision).await?)
    }

    // ── Drained ack operations (old owner -> coordinator) ────────

    pub async fn put_drained_ack(&self, ack: &PodDrainedAck) -> Result<()> {
        count_call("put_drained_ack");
        let key = self.key(StoreKey::DrainedAck {
            partition: ack.partition,
            pod: &ack.pod_name,
        });
        // The store stamps the millisecond clock so span metrics never
        // depend on each writer remembering to.
        let mut stamped = ack.clone();
        stamped.acked_at_ms = assignment_coordination::util::now_millis();
        Ok(self.inner.put(&key, &stamped, None).await?)
    }

    pub async fn list_drained_acks(&self, partition: u32) -> Result<Vec<PodDrainedAck>> {
        count_call("list_drained_acks");
        let key = self.key(StoreKey::DrainedAcksForPartition(partition));
        Ok(self.inner.list(&key).await?)
    }

    pub async fn delete_drained_acks(&self, partition: u32) -> Result<()> {
        let key = self.key(StoreKey::DrainedAcksForPartition(partition));
        Ok(self.inner.delete_prefix(&key).await?)
    }

    pub async fn watch_drained_acks(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::DrainedAcksPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    pub async fn watch_drained_acks_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_drained_acks_from");
        let key = self.key(StoreKey::DrainedAcksPrefix);
        Ok(self.inner.watch_from(&key, start_revision).await?)
    }

    // ── Warmed ack operations (new owner -> coordinator) ─────────

    pub async fn put_warmed_ack(&self, ack: &PodWarmedAck) -> Result<()> {
        count_call("put_warmed_ack");
        let key = self.key(StoreKey::WarmedAck {
            partition: ack.partition,
            pod: &ack.pod_name,
        });
        // The store stamps the millisecond clock so span metrics never
        // depend on each writer remembering to.
        let mut stamped = ack.clone();
        stamped.acked_at_ms = assignment_coordination::util::now_millis();
        Ok(self.inner.put(&key, &stamped, None).await?)
    }

    pub async fn list_warmed_acks(&self, partition: u32) -> Result<Vec<PodWarmedAck>> {
        count_call("list_warmed_acks");
        let key = self.key(StoreKey::WarmedAcksForPartition(partition));
        Ok(self.inner.list(&key).await?)
    }

    pub async fn delete_warmed_acks(&self, partition: u32) -> Result<()> {
        let key = self.key(StoreKey::WarmedAcksForPartition(partition));
        Ok(self.inner.delete_prefix(&key).await?)
    }

    pub async fn watch_warmed_acks(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::WarmedAcksPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    pub async fn watch_warmed_acks_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_warmed_acks_from");
        let key = self.key(StoreKey::WarmedAcksPrefix);
        Ok(self.inner.watch_from(&key, start_revision).await?)
    }

    // ── Transactional operations ────────────────────────────────

    /// Atomically write assignments and create handoff states.
    /// Returns whether every disposition applied. Each partition's unit
    /// is guarded so it only lands if the world it was computed from is
    /// still the world (an assignment-only unit carries no guard):
    ///
    /// * every handoff key must be absent — concurrent planners (the pod
    ///   watch racing the handoff watch's re-trigger, or a failing-over
    ///   coordinator) can both plan the same partition, and an unguarded
    ///   put would replace the first handoff and orphan its acks;
    /// * every `AssignmentPrecondition` must hold — a handoff's
    ///   `old_owner` is only meaningful if the assignment it was read
    ///   from is unchanged. Without this, a plan whose snapshot predates
    ///   a full create→complete→cleanup cycle of the same partition
    ///   passes the absence guard and drains the wrong pod, leaving the
    ///   real owner unfenced beside the new owner's warm cutoff.
    ///
    /// `replacements` carry cancellations-by-replacement: each swaps the
    /// record at its partition's key — guarded on the `mod_revision` the
    /// planner read — for the successor (or reaffirm) record, deleting
    /// the predecessor's acks in the same transaction. A non-terminal
    /// handoff record is never deleted; it is only ever replaced by the
    /// thing that resolves its stashes.
    pub async fn create_assignments_and_handoffs(
        &self,
        assignments: &[PartitionAssignment],
        handoffs: &[HandoffState],
        preconditions: &[AssignmentPrecondition],
        max_txn_ops: usize,
    ) -> Result<bool> {
        // The handoffs come ready-made, so there is no shared
        // membership to write alongside them.
        let application = self
            .apply_plan(assignments, handoffs, &[], preconditions, None, max_txn_ops)
            .await?;
        Ok(application.conflicted.is_empty())
    }

    /// Apply a plan — creations (absent-guarded) plus
    /// cancellations-by-replacement (mod_revision-guarded) — in
    /// transactions sized to `max_txn_ops`, the server's txn budget.
    ///
    /// Atomicity is per partition, not per plan: every guard protects
    /// one partition's disposition, so a partition's guards and writes
    /// share one transaction, but the plan itself may split. An
    /// unchunked plan past `--max-txn-ops` is rejected as a hard error,
    /// and a coordinator retrying it re-earns the same rejection
    /// forever. A partially applied plan is placement drift the next
    /// reconcile-tick replan heals.
    pub async fn apply_plan(
        &self,
        assignments: &[PartitionAssignment],
        handoffs: &[HandoffState],
        replacements: &[HandoffReplacement],
        preconditions: &[AssignmentPrecondition],
        // The membership the plan's handoffs refer to, re-put
        // (idempotently) in every chunk that references it so no
        // handoff is ever durable with a dangling reference.
        freeze_quorum: Option<(&str, &[String])>,
        max_txn_ops: usize,
    ) -> Result<PlanApplication> {
        count_call("apply_plan");
        let mut units: HashMap<u32, PlanUnit> = HashMap::new();
        fn unit(units: &mut HashMap<u32, PlanUnit>, partition: u32) -> &mut PlanUnit {
            units.entry(partition).or_insert_with(|| PlanUnit {
                partition,
                guards: Vec::new(),
                ops: Vec::new(),
                bytes: 0,
                references_quorum: false,
            })
        }

        for a in assignments {
            let key = self.key(StoreKey::Assignment(a.partition));
            let value = serde_json::to_vec(a)?;
            let u = unit(&mut units, a.partition);
            u.bytes += key.len() + value.len();
            u.ops.push(UnitOp::Put(key, value));
        }
        for h in handoffs {
            let key = self.key(StoreKey::Handoff(h.partition));
            let value = serde_json::to_vec(h)?;
            let u = unit(&mut units, h.partition);
            u.bytes += key.len() + value.len();
            // A key that was never created has create_revision 0 — the
            // canonical etcd existence guard.
            u.bytes += key.len();
            u.guards.push(UnitGuard::Absent(key.clone()));
            u.ops.push(UnitOp::Put(key, value));
            u.references_quorum |= h.freeze_quorum_ref.is_some();
        }
        for r in replacements {
            let partition = r.handoff.partition;
            let key = self.key(StoreKey::Handoff(partition));
            let value = serde_json::to_vec(&r.handoff)?;
            let u = unit(&mut units, partition);
            u.bytes += key.len() + value.len();
            u.bytes += key.len();
            u.guards
                .push(UnitGuard::ModRevision(key.clone(), r.expected_mod_revision));
            for acks in [
                self.key(StoreKey::FreezeAcksForPartition(partition)),
                self.key(StoreKey::DrainedAcksForPartition(partition)),
                self.key(StoreKey::WarmedAcksForPartition(partition)),
            ] {
                // A prefix delete carries `range_end` as well as the
                // key, and they are the same length.
                u.bytes += acks.len() * 2;
                u.ops.push(UnitOp::DeletePrefix(acks));
            }
            u.ops.push(UnitOp::Put(key, value));
            u.references_quorum |= r.handoff.freeze_quorum_ref.is_some();
        }
        for precondition in preconditions {
            let (partition, guard) = match precondition {
                AssignmentPrecondition::UnchangedSince {
                    partition,
                    mod_revision,
                } => (
                    *partition,
                    UnitGuard::ModRevision(
                        self.key(StoreKey::Assignment(*partition)),
                        *mod_revision,
                    ),
                ),
                AssignmentPrecondition::Absent { partition } => (
                    *partition,
                    UnitGuard::Absent(self.key(StoreKey::Assignment(*partition))),
                ),
            };
            let u = unit(&mut units, partition);
            u.bytes += guard.key().len();
            u.guards.push(guard);
        }

        // Partition order, so chunk composition is a function of the
        // plan alone rather than of map iteration.
        let mut units: Vec<PlanUnit> = units.into_values().collect();
        units.sort_by_key(|u| u.partition);

        let quorum = match freeze_quorum {
            Some((id, members)) => Some((
                self.key(StoreKey::FreezeQuorum(id)),
                serde_json::to_vec(members)?,
            )),
            None => None,
        };

        // Totals across chunks, keys and deletes included, so the
        // series keeps its meaning from the one-transaction era.
        let plan_bytes: usize = units.iter().map(|u| u.bytes).sum::<usize>()
            + quorum.as_ref().map_or(0, |(k, v)| k.len() + v.len());
        let total_guards: usize = units.iter().map(|u| u.guards.len()).sum();
        let total_ops: usize = units.iter().map(|u| u.ops.len()).sum();
        metrics::histogram!("personhog_coordination_plan_bytes").record(plan_bytes as f64);
        metrics::histogram!("personhog_coordination_plan_ops", "list" => "guards")
            .record(total_guards as f64);
        metrics::histogram!("personhog_coordination_plan_ops", "list" => "ops")
            .record(total_ops as f64);

        let costs: Vec<(usize, usize)> = units
            .iter()
            .map(|u| (u.guards.len(), u.ops.len()))
            .collect();
        let reserve_ops = usize::from(quorum.is_some());
        let ranges = plan_chunk_ranges(&costs, max_txn_ops, reserve_ops);
        metrics::histogram!("personhog_coordination_plan_chunks").record(ranges.len() as f64);

        let mut application = PlanApplication::default();
        for range in ranges {
            let chunk = &units[range];
            match self.apply_units(chunk, &quorum).await {
                Ok(true) => {
                    application
                        .applied
                        .extend(chunk.iter().map(|u| u.partition));
                    continue;
                }
                Ok(false) => {}
                // The server's effective --max-txn-ops can sit below the
                // configured budget (values drift, a member not yet
                // restarted with a raised flag). Degrade to the per-unit
                // path — under any workable server limit — instead of
                // handing back a rejection the planner retries forever.
                Err(e) if chunk.len() > 1 && is_txn_too_large(&e) => {
                    application.over_budget_chunks += 1;
                    metrics::counter!("personhog_coordination_plan_chunk_over_server_budget_total")
                        .increment(1);
                    tracing::warn!(
                        units = chunk.len(),
                        max_txn_ops,
                        error = %e,
                        "plan chunk exceeds the server txn budget; applying per unit"
                    );
                }
                Err(e) => return Err(e),
            }
            // A failed guard names no key, so retry the chunk one
            // partition at a time: the concurrent write that broke the
            // chunk stands down only the units it actually touched.
            for u in chunk {
                if self.apply_units(std::slice::from_ref(u), &quorum).await? {
                    application.applied.push(u.partition);
                } else {
                    metrics::counter!("personhog_coordination_plan_units_conflicted_total")
                        .increment(1);
                    application.conflicted.push(u.partition);
                }
            }
        }
        Ok(application)
    }

    /// One plan chunk as one transaction: the units' guards and ops,
    /// plus the freeze-quorum write when any unit references it.
    /// Returns whether the transaction applied.
    async fn apply_units(
        &self,
        chunk: &[PlanUnit],
        quorum: &Option<(String, Vec<u8>)>,
    ) -> Result<bool> {
        let mut guards: Vec<Compare> = Vec::new();
        let mut ops: Vec<TxnOp> = Vec::new();
        if let Some((key, value)) = quorum {
            if chunk.iter().any(|u| u.references_quorum) {
                ops.push(TxnOp::put(key.clone(), value.clone(), None));
            }
        }
        for u in chunk {
            for g in &u.guards {
                guards.push(match g {
                    UnitGuard::Absent(key) => {
                        Compare::create_revision(key.clone(), CompareOp::Equal, 0)
                    }
                    UnitGuard::ModRevision(key, rev) => {
                        Compare::mod_revision(key.clone(), CompareOp::Equal, *rev)
                    }
                });
            }
            for op in &u.ops {
                ops.push(match op {
                    UnitOp::Put(key, value) => TxnOp::put(key.clone(), value.clone(), None),
                    UnitOp::DeletePrefix(key) => {
                        TxnOp::delete(key.clone(), Some(DeleteOptions::new().with_prefix()))
                    }
                });
            }
        }
        let txn = Txn::new().when(guards).and_then(ops);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    /// Atomically: set handoff phase to Complete and update the assignment owner.
    ///
    /// Uses compare-and-swap on the handoff key's version to prevent stale
    /// writes (e.g. if another actor already completed or deleted the handoff
    /// between our read and write).
    ///
    /// Returns `Ok(false)` if the handoff was modified concurrently (CAS failed),
    /// or if the record at the key is no longer the attempt the caller
    /// validated.
    ///
    /// The `expected_*` arguments are what make the second case
    /// detectable, and they are not optional rigour. Completion is the
    /// step that writes the assignment, so completing the wrong record
    /// hands the partition to a pod that never froze, drained, or warmed
    /// — while the old owner is still admitting writes — and routers cut
    /// over to it. A `mod_revision` guard alone cannot catch that: it
    /// proves nothing changed since this function's own re-read, not that
    /// the record is the one whose warm was verified.
    ///
    /// **Invariant:** this is the only code path that ever *changes* an
    /// assignment's `owner`. Routers rely on observing handoff Complete
    /// events to update their in-memory routing tables — they do not watch
    /// assignments. Anything that mutates `assignments/{partition}` outside
    /// of this method will be invisible to routers. If we ever need a
    /// force-reassignment ops tool, it should create a handoff record and
    /// let the protocol advance it, not write to the assignment key.
    pub async fn complete_handoff(
        &self,
        partition: u32,
        expected_id: &str,
        expected_phase: crate::types::HandoffPhase,
    ) -> Result<bool> {
        count_call("complete_handoff");
        let handoff_key = self.key(StoreKey::Handoff(partition));

        let (mut handoff, mod_revision) = self
            .inner
            .get_with_mod_revision::<HandoffState>(&handoff_key)
            .await?
            .ok_or_else(|| Error::NotFound(format!("handoff for partition {partition}")))?;

        if handoff.handoff_id != expected_id || handoff.phase != expected_phase {
            return Ok(false);
        }

        handoff.phase = crate::types::HandoffPhase::Complete;
        handoff.phase_entered_at_ms = assignment_coordination::util::now_millis();

        let assignment = PartitionAssignment {
            partition,
            owner: handoff.new_owner.clone(),
            advertise_address: handoff.new_owner_address.clone(),
            status: AssignmentStatus::Active,
        };

        let assignment_key = self.key(StoreKey::Assignment(partition));

        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                handoff_key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![
                TxnOp::put(handoff_key, serde_json::to_vec(&handoff)?, None),
                TxnOp::put(assignment_key, serde_json::to_vec(&assignment)?, None),
            ]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    // ── Freeze quorum membership ────────────────────────────────

    /// The membership record `id` names, or `None` if no record exists.
    ///
    /// Callers treat a missing record as "no membership recorded" and
    /// fall back to requiring every live router, which is the stricter
    /// rule — so a record lost to garbage collection or an incomplete
    /// write delays a handoff rather than advancing it early.
    pub async fn get_freeze_quorum(&self, id: &str) -> Result<Option<Vec<String>>> {
        count_call("get_freeze_quorum");
        let key = self.key(StoreKey::FreezeQuorum(id));
        Ok(self.inner.get(&key).await?)
    }

    /// The membership a handoff requires, from wherever it is recorded.
    ///
    /// Records written before the membership moved into its own key
    /// carry it inline. `None` — no reference and nothing inline, or a
    /// reference whose record has gone — means the caller falls back to
    /// requiring every live router.
    pub async fn resolve_freeze_quorum(
        &self,
        handoff: &HandoffState,
    ) -> Result<Option<Vec<String>>> {
        match &handoff.freeze_quorum_ref {
            Some(id) => {
                // A hit answers from memory: confirming against etcd
                // would cost the read this cache removes.
                let cached = self
                    .freeze_quorums
                    .lock()
                    .expect("freeze quorum cache lock poisoned")
                    .get(id)
                    .cloned();
                if let Some(members) = cached {
                    return Ok(Some(members));
                }
                let members = self.get_freeze_quorum(id).await?;
                match &members {
                    Some(recorded) => {
                        let mut cache = self
                            .freeze_quorums
                            .lock()
                            .expect("freeze quorum cache lock poisoned");
                        // Sized for a rolling deploy (plans in flight,
                        // not one). Evicting the oldest — ids lead with
                        // milliseconds, so smallest is oldest — keeps
                        // the working set.
                        if cache.len() >= 32 {
                            if let Some(oldest) = cache.keys().min().cloned() {
                                cache.remove(&oldest);
                            }
                        }
                        cache.insert(id.clone(), recorded.clone());
                    }
                    // Never cached: a chunked plan's re-puts can
                    // re-create a swept record, so absence is not
                    // permanent — and pinning it would hold every later
                    // resolution on the every-live-router fallback.
                    None => {
                        crate::util::record_unresolved_freeze_quorum();
                        tracing::warn!(
                            partition = handoff.partition,
                            quorum_id = %id,
                            "freeze quorum record is missing; requiring every live router"
                        );
                    }
                }
                Ok(members)
            }
            None => Ok(handoff.freeze_quorum.clone()),
        }
    }

    /// The ids of every membership record currently stored, each with
    /// its mod_revision for the sweep's guarded delete.
    pub async fn list_freeze_quorum_ids(&self) -> Result<Vec<(String, i64)>> {
        count_call("list_freeze_quorum_ids");
        let prefix = self.key(StoreKey::FreezeQuorumsPrefix);
        let keys = self.inner.list_keys_with_mod_revisions(&prefix).await?;
        Ok(keys
            .iter()
            .filter_map(|(key, rev)| {
                key.strip_prefix(prefix.as_str())
                    .map(|id| (id.to_string(), *rev))
            })
            .collect())
    }

    /// Delete a membership record only if unchanged since `mod_revision`.
    /// A chunked plan re-puts its record with every chunk, so a re-put
    /// after the sweep's read bumps the revision and the delete loses —
    /// otherwise the sweep could collect a record a chunk it never saw
    /// still references.
    pub async fn delete_freeze_quorum_if_unchanged(
        &self,
        id: &str,
        mod_revision: i64,
    ) -> Result<bool> {
        count_call("delete_freeze_quorum");
        let key = self.key(StoreKey::FreezeQuorum(id));
        let txn = Txn::new()
            .when(vec![Compare::mod_revision(
                key.clone(),
                CompareOp::Equal,
                mod_revision,
            )])
            .and_then(vec![TxnOp::delete(key, None)]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    // ── Leader election ─────────────────────────────────────────

    /// Try to acquire coordinator leadership using compare-and-swap.
    ///
    /// Returns `true` if this instance became the leader.
    pub async fn try_acquire_leadership(&self, holder: &str, lease_id: i64) -> Result<bool> {
        count_call("try_acquire_leadership");
        let key = self.key(StoreKey::Leader);
        let leader = LeaderInfo {
            holder: holder.to_string(),
            lease_id,
        };
        let value = serde_json::to_vec(&leader)?;

        // CAS: only succeed if the key does not exist (version == 0)
        let txn = Txn::new()
            .when(vec![Compare::version(key.clone(), CompareOp::Equal, 0)])
            .and_then(vec![TxnOp::put(
                key.clone(),
                value,
                Some(PutOptions::new().with_lease(lease_id)),
            )])
            .or_else(vec![TxnOp::get(key, None)]);

        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    pub async fn get_leader(&self) -> Result<Option<LeaderInfo>> {
        count_call("get_leader");
        let key = self.key(StoreKey::Leader);
        Ok(self.inner.get(&key).await?)
    }

    /// The current leader and the revision that answer was read at. A
    /// standby anchors its watch on that revision so the leader cannot
    /// disappear unobserved in the gap before the watch attaches.
    pub async fn get_leader_with_revision(&self) -> Result<(Option<LeaderInfo>, i64)> {
        count_call("get_leader_with_revision");
        let key = self.key(StoreKey::Leader);
        Ok(self.inner.get_with_revision(&key).await?)
    }

    /// Watch the leader key alone, from `start_revision` inclusive.
    pub async fn watch_leader_from(&self, start_revision: i64) -> Result<WatchStream> {
        count_call("watch_leader_from");
        let key = self.key(StoreKey::Leader);
        Ok(self.inner.watch_key_from(&key, start_revision).await?)
    }

    // ── Lease operations ────────────────────────────────────────

    pub async fn grant_lease(&self, ttl: i64) -> Result<i64> {
        count_call("grant_lease");
        Ok(self.inner.grant_lease(ttl).await?)
    }

    pub async fn keep_alive(
        &self,
        lease_id: i64,
    ) -> Result<(etcd_client::LeaseKeeper, etcd_client::LeaseKeepAliveStream)> {
        count_call("keep_alive");
        Ok(self.inner.keep_alive(lease_id).await?)
    }

    pub async fn revoke_lease(&self, lease_id: i64) -> Result<()> {
        count_call("revoke_lease");
        Ok(self.inner.revoke_lease(lease_id).await?)
    }

    // ── Config operations ───────────────────────────────────────

    pub async fn get_total_partitions(&self) -> Result<u32> {
        count_call("get_total_partitions");
        let key = self.key(StoreKey::TotalPartitions);
        let bytes = self
            .inner
            .get_raw(&key)
            .await?
            .ok_or_else(|| Error::NotFound(key))?;
        let s = from_utf8(&bytes)
            .map_err(|e| Error::invalid_state(format!("non-utf8 total_partitions: {e}")))?;
        s.parse::<u32>()
            .map_err(|e| Error::invalid_state(format!("invalid total_partitions: {e}")))
    }

    pub async fn set_total_partitions(&self, count: u32) -> Result<()> {
        let key = self.key(StoreKey::TotalPartitions);
        Ok(self.inner.put_raw(&key, count.to_string()).await?)
    }

    pub async fn get_generation(&self) -> Result<String> {
        let key = self.key(StoreKey::Generation);
        let bytes = self
            .inner
            .get_raw(&key)
            .await?
            .ok_or_else(|| Error::NotFound(key))?;
        String::from_utf8(bytes)
            .map_err(|e| Error::invalid_state(format!("non-utf8 generation: {e}")))
    }

    pub async fn set_generation(&self, generation: &str) -> Result<()> {
        let key = self.key(StoreKey::Generation);
        Ok(self.inner.put_raw(&key, generation).await?)
    }

    // ── Cleanup ─────────────────────────────────────────────────

    /// Delete all keys under the store's prefix.
    pub async fn delete_all(&self) -> Result<()> {
        Ok(self.inner.delete_all().await?)
    }
}

/// Extract a partition number from an etcd key like `{prefix}assignments/42`.
pub fn extract_partition_from_key(key: &str) -> Option<u32> {
    key.rsplit('/').next()?.parse().ok()
}

/// Extract the second-to-last segment as a partition number from keys like
/// `{prefix}handoff_acks/42/router-0`.
pub fn extract_partition_from_ack_key(key: &str) -> Option<u32> {
    let parts: Vec<&str> = key.rsplitn(3, '/').collect();
    if parts.len() >= 2 {
        parts[1].parse().ok()
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::plan_chunk_ranges;

    /// Every unit lands in exactly one chunk, in order — chunking must
    /// never drop or reorder a partition's disposition.
    fn assert_contiguous_cover(ranges: &[std::ops::Range<usize>], len: usize) {
        let mut next = 0;
        for r in ranges {
            assert_eq!(r.start, next, "chunks must be contiguous");
            assert!(r.end > r.start, "chunks must be non-empty");
            next = r.end;
        }
        assert_eq!(next, len, "chunks must cover every unit");
    }

    /// The 256→1 collapse shape: 256 creations of (2 guards, 1 op)
    /// against etcd's default budget. The compare list is what binds —
    /// an unchunked plan carries 512 compares and is rejected outright.
    #[test]
    fn creations_chunk_on_the_compare_list() {
        let costs = vec![(2, 1); 256];
        let ranges = plan_chunk_ranges(&costs, 128, 1);
        assert_contiguous_cover(&ranges, costs.len());
        for r in &ranges {
            let guards: usize = costs[r.clone()].iter().map(|c| c.0).sum();
            let ops: usize = costs[r.clone()].iter().map(|c| c.1).sum();
            assert!(guards <= 128, "chunk carries {guards} compares");
            assert!(ops < 128, "chunk carries {ops} ops plus the quorum write");
        }
        assert_eq!(
            ranges.len(),
            4,
            "512 compares over a 128 budget is 4 chunks"
        );
    }

    /// The mass-cancellation shape: replacements cost (2 guards, 4 ops),
    /// so the op list binds, and the reserved quorum write counts
    /// against every chunk.
    #[test]
    fn replacements_chunk_on_the_op_list_with_the_reserve() {
        let costs = vec![(2, 4); 256];
        let ranges = plan_chunk_ranges(&costs, 128, 1);
        assert_contiguous_cover(&ranges, costs.len());
        for r in &ranges {
            let ops: usize = costs[r.clone()].iter().map(|c| c.1).sum();
            assert!(ops < 128, "chunk carries {ops} ops plus the quorum write");
        }
    }

    /// A plan that fits stays one transaction — chunking must not tax
    /// the healthy case with extra round trips.
    #[test]
    fn a_fitting_plan_is_one_chunk() {
        let costs = vec![(2, 1); 60];
        assert_eq!(plan_chunk_ranges(&costs, 128, 1), vec![0..60]);
    }

    /// A budget below a single unit's cost still emits that unit alone:
    /// the packer must make progress and let the server be the judge.
    #[test]
    fn an_oversized_unit_is_its_own_chunk() {
        let costs = vec![(2, 4), (2, 4)];
        assert_eq!(plan_chunk_ranges(&costs, 1, 0), vec![0..1, 1..2]);
    }
}
