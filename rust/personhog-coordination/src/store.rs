use assignment_coordination::store::EtcdStore;
use etcd_client::{Compare, CompareOp, PutOptions, Txn, TxnOp, WatchStream};

use crate::error::{Error, Result};
use crate::types::{
    AssignmentStatus, HandoffState, LeaderInfo, PartitionAssignment, PodDrainedAck, PodStatus,
    PodWarmedAck, RegisteredPod, RegisteredRouter, RouterFreezeAck,
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
}

impl PersonhogStore {
    pub fn new(inner: EtcdStore) -> Self {
        Self { inner }
    }

    pub fn inner(&self) -> &EtcdStore {
        &self.inner
    }

    fn key(&self, k: StoreKey<'_>) -> String {
        k.resolve(self.inner.prefix())
    }

    // ── Pod operations ──────────────────────────────────────────

    pub async fn register_pod(&self, pod: &RegisteredPod, lease_id: i64) -> Result<()> {
        let key = self.key(StoreKey::Pod(&pod.pod_name));
        Ok(self.inner.put(&key, pod, Some(lease_id)).await?)
    }

    pub async fn get_pod(&self, pod_name: &str) -> Result<Option<RegisteredPod>> {
        let key = self.key(StoreKey::Pod(pod_name));
        Ok(self.inner.get(&key).await?)
    }

    pub async fn delete_pod(&self, pod_name: &str) -> Result<()> {
        let key = self.key(StoreKey::Pod(pod_name));
        Ok(self.inner.delete(&key).await?)
    }

    pub async fn list_pods(&self) -> Result<Vec<RegisteredPod>> {
        let key = self.key(StoreKey::PodsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn update_pod_status(
        &self,
        pod_name: &str,
        status: PodStatus,
        lease_id: i64,
    ) -> Result<()> {
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

    // ── Router operations ────────────────────────────────────────

    pub async fn register_router(&self, router: &RegisteredRouter, lease_id: i64) -> Result<()> {
        let key = self.key(StoreKey::Router(&router.router_name));
        Ok(self.inner.put(&key, router, Some(lease_id)).await?)
    }

    pub async fn list_routers(&self) -> Result<Vec<RegisteredRouter>> {
        let key = self.key(StoreKey::RoutersPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn watch_routers(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::RoutersPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    // ── Assignment operations ───────────────────────────────────

    pub async fn get_assignment(&self, partition: u32) -> Result<Option<PartitionAssignment>> {
        let key = self.key(StoreKey::Assignment(partition));
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_assignments(&self) -> Result<Vec<PartitionAssignment>> {
        let key = self.key(StoreKey::AssignmentsPrefix);
        Ok(self.inner.list(&key).await?)
    }

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
        let key = self.key(StoreKey::Handoff(partition));
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_handoffs(&self) -> Result<Vec<HandoffState>> {
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn put_handoff(&self, handoff: &HandoffState) -> Result<()> {
        let key = self.key(StoreKey::Handoff(handoff.partition));
        Ok(self.inner.put(&key, handoff, None).await?)
    }

    /// Compare-and-swap a handoff's phase. Reads the current handoff,
    /// verifies its phase matches `expected`, and writes a copy with
    /// `new_phase` only if the etcd key version hasn't changed.
    ///
    /// Returns `Ok(true)` if the swap succeeded, `Ok(false)` if the handoff
    /// was concurrently modified or its phase no longer matches `expected`.
    /// Used by `check_phase_advance` to avoid duplicate phase writes when
    /// multiple watch loops fire `check_phase_advance` concurrently for the
    /// same partition.
    pub async fn cas_handoff_phase(
        &self,
        partition: u32,
        expected: crate::types::HandoffPhase,
        new_phase: crate::types::HandoffPhase,
    ) -> Result<bool> {
        let handoff_key = self.key(StoreKey::Handoff(partition));
        let Some((mut handoff, version)) = self
            .inner
            .get_versioned::<HandoffState>(&handoff_key)
            .await?
        else {
            return Ok(false);
        };
        if handoff.phase != expected {
            return Ok(false);
        }
        handoff.phase = new_phase;
        let txn = Txn::new()
            .when(vec![Compare::version(
                handoff_key.clone(),
                CompareOp::Equal,
                version,
            )])
            .and_then(vec![TxnOp::put(
                handoff_key,
                serde_json::to_vec(&handoff)?,
                None,
            )]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    pub async fn delete_handoff(&self, partition: u32) -> Result<()> {
        let key = self.key(StoreKey::Handoff(partition));
        Ok(self.inner.delete(&key).await?)
    }

    pub async fn watch_handoffs(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    // ── Freeze ack operations (router -> coordinator) ────────────

    pub async fn put_freeze_ack(&self, ack: &RouterFreezeAck) -> Result<()> {
        let key = self.key(StoreKey::FreezeAck {
            partition: ack.partition,
            router: &ack.router_name,
        });
        Ok(self.inner.put(&key, ack, None).await?)
    }

    pub async fn list_freeze_acks(&self, partition: u32) -> Result<Vec<RouterFreezeAck>> {
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

    // ── Drained ack operations (old owner -> coordinator) ────────

    pub async fn put_drained_ack(&self, ack: &PodDrainedAck) -> Result<()> {
        let key = self.key(StoreKey::DrainedAck {
            partition: ack.partition,
            pod: &ack.pod_name,
        });
        Ok(self.inner.put(&key, ack, None).await?)
    }

    pub async fn list_drained_acks(&self, partition: u32) -> Result<Vec<PodDrainedAck>> {
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

    // ── Warmed ack operations (new owner -> coordinator) ─────────

    pub async fn put_warmed_ack(&self, ack: &PodWarmedAck) -> Result<()> {
        let key = self.key(StoreKey::WarmedAck {
            partition: ack.partition,
            pod: &ack.pod_name,
        });
        Ok(self.inner.put(&key, ack, None).await?)
    }

    pub async fn list_warmed_acks(&self, partition: u32) -> Result<Vec<PodWarmedAck>> {
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

    /// Clean up every handoff-related ack for a partition. Called when a
    /// handoff is completed or cancelled.
    pub async fn delete_all_handoff_acks(&self, partition: u32) -> Result<()> {
        self.delete_freeze_acks(partition).await?;
        self.delete_drained_acks(partition).await?;
        self.delete_warmed_acks(partition).await?;
        Ok(())
    }

    // ── Transactional operations ────────────────────────────────

    /// Atomically write assignments and create handoff states.
    pub async fn create_assignments_and_handoffs(
        &self,
        assignments: &[PartitionAssignment],
        handoffs: &[HandoffState],
    ) -> Result<()> {
        let mut ops: Vec<TxnOp> = Vec::with_capacity(assignments.len() + handoffs.len());

        for a in assignments {
            let key = self.key(StoreKey::Assignment(a.partition));
            let value = serde_json::to_vec(a)?;
            ops.push(TxnOp::put(key, value, None));
        }
        for h in handoffs {
            let key = self.key(StoreKey::Handoff(h.partition));
            let value = serde_json::to_vec(h)?;
            ops.push(TxnOp::put(key, value, None));
        }

        let txn = Txn::new().and_then(ops);
        self.inner.txn(txn).await?;
        Ok(())
    }

    /// Atomically: set handoff phase to Complete and update the assignment owner.
    ///
    /// Uses compare-and-swap on the handoff key's version to prevent stale
    /// writes (e.g. if another actor already completed or deleted the handoff
    /// between our read and write).
    ///
    /// Returns `Ok(false)` if the handoff was modified concurrently (CAS failed).
    ///
    /// **Invariant:** this is the only code path that ever *changes* an
    /// assignment's `owner`. Routers rely on observing handoff Complete
    /// events to update their in-memory routing tables — they do not watch
    /// assignments. Anything that mutates `assignments/{partition}` outside
    /// of this method will be invisible to routers. If we ever need a
    /// force-reassignment ops tool, it should create a handoff record and
    /// let the protocol advance it, not write to the assignment key.
    pub async fn complete_handoff(&self, partition: u32) -> Result<bool> {
        let handoff_key = self.key(StoreKey::Handoff(partition));

        let (mut handoff, version) = self
            .inner
            .get_versioned::<HandoffState>(&handoff_key)
            .await?
            .ok_or_else(|| Error::NotFound(format!("handoff for partition {partition}")))?;

        handoff.phase = crate::types::HandoffPhase::Complete;

        let assignment = PartitionAssignment {
            partition,
            owner: handoff.new_owner.clone(),
            status: AssignmentStatus::Active,
        };

        let assignment_key = self.key(StoreKey::Assignment(partition));

        let txn = Txn::new()
            .when(vec![Compare::version(
                handoff_key.clone(),
                CompareOp::Equal,
                version,
            )])
            .and_then(vec![
                TxnOp::put(handoff_key, serde_json::to_vec(&handoff)?, None),
                TxnOp::put(assignment_key, serde_json::to_vec(&assignment)?, None),
            ]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    // ── Leader election ─────────────────────────────────────────

    /// Try to acquire coordinator leadership using compare-and-swap.
    ///
    /// Returns `true` if this instance became the leader.
    pub async fn try_acquire_leadership(&self, holder: &str, lease_id: i64) -> Result<bool> {
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
        let key = self.key(StoreKey::Leader);
        Ok(self.inner.get(&key).await?)
    }

    // ── Lease operations ────────────────────────────────────────

    pub async fn grant_lease(&self, ttl: i64) -> Result<i64> {
        Ok(self.inner.grant_lease(ttl).await?)
    }

    pub async fn keep_alive(
        &self,
        lease_id: i64,
    ) -> Result<(etcd_client::LeaseKeeper, etcd_client::LeaseKeepAliveStream)> {
        Ok(self.inner.keep_alive(lease_id).await?)
    }

    pub async fn revoke_lease(&self, lease_id: i64) -> Result<()> {
        Ok(self.inner.revoke_lease(lease_id).await?)
    }

    // ── Config operations ───────────────────────────────────────

    pub async fn get_total_partitions(&self) -> Result<u32> {
        let key = self.key(StoreKey::TotalPartitions);
        let bytes = self
            .inner
            .get_raw(&key)
            .await?
            .ok_or_else(|| Error::NotFound(key))?;
        let s = std::str::from_utf8(&bytes)
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
