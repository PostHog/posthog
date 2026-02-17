use etcd_client::{
    Client, Compare, CompareOp, DeleteOptions, GetOptions, PutOptions, Txn, TxnOp, WatchOptions,
    WatchStream,
};
use serde::de::DeserializeOwned;
use serde::Serialize;

use crate::error::{Error, Result};
use crate::types::{
    AssignmentStatus, HandoffState, LeaderInfo, PartitionAssignment, PodStatus, RegisteredPod,
    RegisteredRouter, RouterCutoverAck,
};

#[derive(Debug, Clone)]
pub struct StoreConfig {
    pub endpoints: Vec<String>,
    /// Key prefix for all operations (e.g., "/personhog/" or "/test-{uuid}/").
    pub prefix: String,
}

/// All etcd key patterns used by the store.
enum StoreKey<'a> {
    Pod(&'a str),
    PodsPrefix,
    Router(&'a str),
    RoutersPrefix,
    Assignment(u32),
    AssignmentsPrefix,
    Handoff(u32),
    HandoffsPrefix,
    HandoffAck { partition: u32, router: &'a str },
    HandoffAcksForPartition(u32),
    HandoffAcksPrefix,
    Leader,
    Generation,
    Config(&'a str),
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
            StoreKey::HandoffAck { partition, router } => {
                format!("{prefix}handoff_acks/{partition}/{router}")
            }
            StoreKey::HandoffAcksForPartition(p) => format!("{prefix}handoff_acks/{p}/"),
            StoreKey::HandoffAcksPrefix => format!("{prefix}handoff_acks/"),
            StoreKey::Leader => format!("{prefix}coordinator/leader"),
            StoreKey::Generation => format!("{prefix}generation"),
            StoreKey::Config(name) => format!("{prefix}config/{name}"),
        }
    }
}

/// Typed wrapper around etcd for all PersonHog coordination state.
///
/// `Client` is `Clone` (it wraps an inner `Arc`), so each method clones it.
#[derive(Clone)]
pub struct EtcdStore {
    client: Client,
    config: StoreConfig,
}

impl EtcdStore {
    pub async fn connect(config: StoreConfig) -> Result<Self> {
        let client = Client::connect(&config.endpoints, None).await?;
        Ok(Self { client, config })
    }

    fn key(&self, k: StoreKey<'_>) -> String {
        k.resolve(&self.config.prefix)
    }

    // ── Generic helpers ──────────────────────────────────────────

    async fn get_json<T: DeserializeOwned>(&self, key: String) -> Result<Option<T>> {
        let resp = self.client.clone().get(key, None).await?;
        match resp.kvs().first() {
            Some(kv) => Ok(Some(serde_json::from_slice(kv.value())?)),
            None => Ok(None),
        }
    }

    async fn list_json<T: DeserializeOwned>(&self, prefix: String) -> Result<Vec<T>> {
        let options = GetOptions::new().with_prefix();
        let resp = self.client.clone().get(prefix, Some(options)).await?;
        resp.kvs()
            .iter()
            .map(|kv| serde_json::from_slice(kv.value()).map_err(Error::from))
            .collect()
    }

    async fn put_json<T: Serialize>(
        &self,
        key: String,
        value: &T,
        lease_id: Option<i64>,
    ) -> Result<()> {
        let value = serde_json::to_string(value)?;
        let options = lease_id.map(|id| PutOptions::new().with_lease(id));
        self.client.clone().put(key, value, options).await?;
        Ok(())
    }

    async fn delete_key(&self, key: String) -> Result<()> {
        self.client.clone().delete(key, None).await?;
        Ok(())
    }

    async fn delete_by_prefix(&self, prefix: String) -> Result<()> {
        let options = DeleteOptions::new().with_prefix();
        self.client.clone().delete(prefix, Some(options)).await?;
        Ok(())
    }

    async fn watch_by_prefix(&self, prefix: String) -> Result<WatchStream> {
        let options = WatchOptions::new().with_prefix();
        let stream = self.client.clone().watch(prefix, Some(options)).await?;
        Ok(stream)
    }

    // ── Pod operations ──────────────────────────────────────────

    pub async fn register_pod(&self, pod: &RegisteredPod, lease_id: i64) -> Result<()> {
        self.put_json(self.key(StoreKey::Pod(&pod.pod_name)), pod, Some(lease_id))
            .await
    }

    pub async fn get_pod(&self, pod_name: &str) -> Result<Option<RegisteredPod>> {
        self.get_json(self.key(StoreKey::Pod(pod_name))).await
    }

    pub async fn list_pods(&self) -> Result<Vec<RegisteredPod>> {
        self.list_json(self.key(StoreKey::PodsPrefix)).await
    }

    pub async fn update_pod_status(&self, pod_name: &str, status: PodStatus) -> Result<()> {
        let key = self.key(StoreKey::Pod(pod_name));
        let mut pod: RegisteredPod = self
            .get_json(key.clone())
            .await?
            .ok_or_else(|| Error::NotFound(format!("pod {pod_name}")))?;
        pod.status = status;
        self.put_json(key, &pod, None).await
    }

    pub async fn watch_pods(&self) -> Result<WatchStream> {
        self.watch_by_prefix(self.key(StoreKey::PodsPrefix)).await
    }

    // ── Router operations ────────────────────────────────────────

    pub async fn register_router(&self, router: &RegisteredRouter, lease_id: i64) -> Result<()> {
        self.put_json(
            self.key(StoreKey::Router(&router.router_name)),
            router,
            Some(lease_id),
        )
        .await
    }

    pub async fn list_routers(&self) -> Result<Vec<RegisteredRouter>> {
        self.list_json(self.key(StoreKey::RoutersPrefix)).await
    }

    pub async fn watch_routers(&self) -> Result<WatchStream> {
        self.watch_by_prefix(self.key(StoreKey::RoutersPrefix))
            .await
    }

    // ── Assignment operations ───────────────────────────────────

    pub async fn get_assignment(&self, partition: u32) -> Result<Option<PartitionAssignment>> {
        self.get_json(self.key(StoreKey::Assignment(partition)))
            .await
    }

    pub async fn list_assignments(&self) -> Result<Vec<PartitionAssignment>> {
        self.list_json(self.key(StoreKey::AssignmentsPrefix)).await
    }

    pub async fn put_assignments(&self, assignments: &[PartitionAssignment]) -> Result<()> {
        if assignments.is_empty() {
            return Ok(());
        }
        let ops: Vec<TxnOp> = assignments
            .iter()
            .map(|a| {
                let key = self.key(StoreKey::Assignment(a.partition));
                let value = serde_json::to_vec(a).expect("serialize assignment");
                TxnOp::put(key, value, None)
            })
            .collect();
        let txn = Txn::new().and_then(ops);
        self.client.clone().txn(txn).await?;
        Ok(())
    }

    pub async fn watch_assignments(&self) -> Result<WatchStream> {
        self.watch_by_prefix(self.key(StoreKey::AssignmentsPrefix))
            .await
    }

    // ── Handoff operations ──────────────────────────────────────

    pub async fn get_handoff(&self, partition: u32) -> Result<Option<HandoffState>> {
        self.get_json(self.key(StoreKey::Handoff(partition))).await
    }

    pub async fn list_handoffs(&self) -> Result<Vec<HandoffState>> {
        self.list_json(self.key(StoreKey::HandoffsPrefix)).await
    }

    pub async fn put_handoff(&self, handoff: &HandoffState) -> Result<()> {
        self.put_json(
            self.key(StoreKey::Handoff(handoff.partition)),
            handoff,
            None,
        )
        .await
    }

    pub async fn delete_handoff(&self, partition: u32) -> Result<()> {
        self.delete_key(self.key(StoreKey::Handoff(partition)))
            .await
    }

    pub async fn watch_handoffs(&self) -> Result<WatchStream> {
        self.watch_by_prefix(self.key(StoreKey::HandoffsPrefix))
            .await
    }

    // ── Router cutover ack operations ────────────────────────────

    pub async fn put_router_ack(&self, ack: &RouterCutoverAck) -> Result<()> {
        let key = self.key(StoreKey::HandoffAck {
            partition: ack.partition,
            router: &ack.router_name,
        });
        self.put_json(key, ack, None).await
    }

    pub async fn list_router_acks(&self, partition: u32) -> Result<Vec<RouterCutoverAck>> {
        self.list_json(self.key(StoreKey::HandoffAcksForPartition(partition)))
            .await
    }

    pub async fn delete_router_acks(&self, partition: u32) -> Result<()> {
        self.delete_by_prefix(self.key(StoreKey::HandoffAcksForPartition(partition)))
            .await
    }

    pub async fn watch_handoff_acks(&self) -> Result<WatchStream> {
        self.watch_by_prefix(self.key(StoreKey::HandoffAcksPrefix))
            .await
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
        self.client.clone().txn(txn).await?;
        Ok(())
    }

    /// Atomically: set handoff phase to Complete and update the assignment owner.
    pub async fn complete_handoff(&self, partition: u32) -> Result<()> {
        let mut handoff = self
            .get_handoff(partition)
            .await?
            .ok_or_else(|| Error::NotFound(format!("handoff for partition {partition}")))?;

        handoff.phase = crate::types::HandoffPhase::Complete;

        let assignment = PartitionAssignment {
            partition,
            owner: handoff.new_owner.clone(),
            status: AssignmentStatus::Active,
        };

        let handoff_key = self.key(StoreKey::Handoff(partition));
        let assignment_key = self.key(StoreKey::Assignment(partition));

        let txn = Txn::new().and_then(vec![
            TxnOp::put(handoff_key, serde_json::to_vec(&handoff)?, None),
            TxnOp::put(assignment_key, serde_json::to_vec(&assignment)?, None),
        ]);
        self.client.clone().txn(txn).await?;
        Ok(())
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

        let resp = self.client.clone().txn(txn).await?;
        Ok(resp.succeeded())
    }

    pub async fn get_leader(&self) -> Result<Option<LeaderInfo>> {
        self.get_json(self.key(StoreKey::Leader)).await
    }

    // ── Lease operations ────────────────────────────────────────

    pub async fn grant_lease(&self, ttl: i64) -> Result<i64> {
        let resp = self.client.clone().lease_grant(ttl, None).await?;
        Ok(resp.id())
    }

    pub async fn keep_alive(
        &self,
        lease_id: i64,
    ) -> Result<(etcd_client::LeaseKeeper, etcd_client::LeaseKeepAliveStream)> {
        let (keeper, stream) = self.client.clone().lease_keep_alive(lease_id).await?;
        Ok((keeper, stream))
    }

    pub async fn revoke_lease(&self, lease_id: i64) -> Result<()> {
        self.client.clone().lease_revoke(lease_id).await?;
        Ok(())
    }

    // ── Config operations ───────────────────────────────────────

    pub async fn get_total_partitions(&self) -> Result<u32> {
        let key = self.key(StoreKey::Config("total_partitions"));
        let resp = self.client.clone().get(key.clone(), None).await?;
        let kv = resp.kvs().first().ok_or_else(|| Error::NotFound(key))?;
        let s = std::str::from_utf8(kv.value())
            .map_err(|e| Error::InvalidState(format!("non-utf8 total_partitions: {e}")))?;
        s.parse::<u32>()
            .map_err(|e| Error::InvalidState(format!("invalid total_partitions: {e}")))
    }

    pub async fn set_total_partitions(&self, count: u32) -> Result<()> {
        let key = self.key(StoreKey::Config("total_partitions"));
        self.client
            .clone()
            .put(key, count.to_string(), None)
            .await?;
        Ok(())
    }

    pub async fn get_generation(&self) -> Result<String> {
        let key = self.key(StoreKey::Generation);
        let resp = self.client.clone().get(key.clone(), None).await?;
        let kv = resp.kvs().first().ok_or_else(|| Error::NotFound(key))?;
        String::from_utf8(kv.value().to_vec())
            .map_err(|e| Error::InvalidState(format!("non-utf8 generation: {e}")))
    }

    pub async fn set_generation(&self, generation: &str) -> Result<()> {
        let key = self.key(StoreKey::Generation);
        self.client.clone().put(key, generation, None).await?;
        Ok(())
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

/// Parse a watch event's value as JSON into type `T`.
pub fn parse_watch_value<T: serde::de::DeserializeOwned>(
    event: &etcd_client::Event,
) -> std::result::Result<T, Error> {
    let kv = event
        .kv()
        .ok_or_else(|| Error::InvalidState("watch event missing kv".to_string()))?;
    serde_json::from_slice(kv.value()).map_err(Error::from)
}
