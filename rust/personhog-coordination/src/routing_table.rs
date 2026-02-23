use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use etcd_client::EventType;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;

use crate::error::{Error, Result};
use crate::store::{self, EtcdStore};
use crate::types::{
    HandoffPhase, HandoffState, PartitionAssignment, RegisteredRouter, RouterCutoverAck,
};
use crate::util;

/// Trait for the router-side cutover handler.
///
/// Implementations perform the actual traffic cutover: stop routing to the old
/// pod, stash new requests, wait for inflight to complete, then switch to the
/// new pod and flush stashed requests.
#[async_trait]
pub trait CutoverHandler: Send + Sync {
    async fn execute_cutover(&self, partition: u32, old_owner: &str, new_owner: &str)
        -> Result<()>;
}

/// Configuration for the routing table.
#[derive(Debug, Clone)]
pub struct RoutingTableConfig {
    pub router_name: String,
    pub lease_ttl: i64,
    pub heartbeat_interval: Duration,
}

impl Default for RoutingTableConfig {
    fn default() -> Self {
        Self {
            router_name: "router-0".to_string(),
            lease_ttl: 30,
            heartbeat_interval: Duration::from_secs(10),
        }
    }
}

/// Routing table that watches etcd assignments and handoffs.
///
/// Maintains the current partition-to-pod mapping. When a handoff reaches
/// the `Ready` phase, calls the `CutoverHandler` to perform the traffic
/// switch, then writes a `RouterCutoverAck` to etcd.
pub struct RoutingTable {
    store: Arc<EtcdStore>,
    config: RoutingTableConfig,
    handler: Arc<dyn CutoverHandler>,
    table: Arc<RwLock<HashMap<u32, String>>>,
}

impl RoutingTable {
    pub fn new(
        store: Arc<EtcdStore>,
        config: RoutingTableConfig,
        handler: Arc<dyn CutoverHandler>,
    ) -> Self {
        Self {
            store,
            config,
            handler,
            table: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Look up the current owner of a partition.
    pub async fn lookup(&self, partition: u32) -> Option<String> {
        self.table.read().await.get(&partition).cloned()
    }

    /// Return a snapshot of the full routing map.
    pub async fn snapshot(&self) -> HashMap<u32, String> {
        self.table.read().await.clone()
    }

    /// Return a shared handle to the routing table.
    ///
    /// Useful for tests that need to inspect the table after moving the
    /// `RoutingTable` into a spawned task.
    pub fn table_handle(&self) -> Arc<RwLock<HashMap<u32, String>>> {
        Arc::clone(&self.table)
    }

    /// Run the routing table. Registers with etcd, loads the initial state,
    /// then watches for assignment changes and handoffs. Blocks until cancelled.
    pub async fn run(&self, cancel: CancellationToken) -> Result<()> {
        // Register this router so the coordinator can count it for ack quorum
        let lease_id = self.store.grant_lease(self.config.lease_ttl).await?;
        self.register_router(lease_id).await?;

        self.load_initial().await?;

        // Run heartbeat, assignment watch, and handoff watch concurrently
        let mut tasks = tokio::task::JoinSet::new();

        {
            let store = Arc::clone(&self.store);
            let interval = self.config.heartbeat_interval;
            let token = cancel.child_token();
            tasks.spawn(async move {
                util::run_lease_keepalive(store, lease_id, interval, token).await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let table = Arc::clone(&self.table);
            let token = cancel.child_token();
            tasks.spawn(async move { Self::watch_assignments_loop(store, table, token).await });
        }

        {
            let store = Arc::clone(&self.store);
            let handler = Arc::clone(&self.handler);
            let router_name = self.config.router_name.clone();
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_handoffs_loop(store, handler, router_name, token).await
            });
        }

        let result = tokio::select! {
            _ = cancel.cancelled() => Ok(()),
            Some(result) = tasks.join_next() => {
                result.map_err(|e| Error::InvalidState(format!("task panicked: {e}")))?
            }
        };

        // Abort and await all remaining tasks for clean shutdown
        tasks.shutdown().await;

        result
    }

    async fn register_router(&self, lease_id: i64) -> Result<()> {
        let now = util::now_seconds();
        let router = RegisteredRouter {
            router_name: self.config.router_name.clone(),
            registered_at: now,
            last_heartbeat: now,
        };
        self.store.register_router(&router, lease_id).await
    }

    async fn load_initial(&self) -> Result<()> {
        let assignments = self.store.list_assignments().await?;
        let mut table = self.table.write().await;
        for a in assignments {
            table.insert(a.partition, a.owner);
        }
        tracing::info!(count = table.len(), "loaded initial routing table");
        drop(table);

        // Catch up on any in-progress handoffs that reached Ready before we
        // started watching. Without this, a late-joining router would never ack
        // these handoffs, blocking completion forever.
        let handoffs = self.store.list_handoffs().await?;
        for handoff in handoffs {
            if handoff.phase == HandoffPhase::Ready {
                tracing::info!(
                    router = %self.config.router_name,
                    partition = handoff.partition,
                    old_owner = %handoff.old_owner,
                    new_owner = %handoff.new_owner,
                    "catching up on in-progress handoff"
                );

                self.handler
                    .execute_cutover(handoff.partition, &handoff.old_owner, &handoff.new_owner)
                    .await?;

                let ack = RouterCutoverAck {
                    router_name: self.config.router_name.clone(),
                    partition: handoff.partition,
                    acked_at: util::now_seconds(),
                };
                self.store.put_router_ack(&ack).await?;
            }
        }

        Ok(())
    }

    async fn watch_assignments_loop(
        store: Arc<EtcdStore>,
        table: Arc<RwLock<HashMap<u32, String>>>,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_assignments().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::InvalidState("assignment watch stream ended".to_string()))?;
                    for event in resp.events() {
                        match event.event_type() {
                            EventType::Put => {
                                let assignment: PartitionAssignment = store::parse_watch_value(event)?;
                                table.write().await.insert(assignment.partition, assignment.owner);
                            }
                            EventType::Delete => {
                                if let Some(kv) = event.kv() {
                                    if let Some(partition) = store::extract_partition_from_key(
                                        std::str::from_utf8(kv.key()).unwrap_or(""),
                                    ) {
                                        table.write().await.remove(&partition);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    async fn watch_handoffs_loop(
        store: Arc<EtcdStore>,
        handler: Arc<dyn CutoverHandler>,
        router_name: String,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_handoffs().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::InvalidState("handoff watch stream ended".to_string()))?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            match store::parse_watch_value::<HandoffState>(event) {
                                Ok(handoff) if handoff.phase == HandoffPhase::Ready => {
                                    tracing::info!(
                                        router = %router_name,
                                        partition = handoff.partition,
                                        old_owner = %handoff.old_owner,
                                        new_owner = %handoff.new_owner,
                                        "executing cutover"
                                    );

                                    handler.execute_cutover(
                                        handoff.partition,
                                        &handoff.old_owner,
                                        &handoff.new_owner,
                                    ).await?;

                                    let ack = RouterCutoverAck {
                                        router_name: router_name.clone(),
                                        partition: handoff.partition,
                                        acked_at: util::now_seconds(),
                                    };
                                    store.put_router_ack(&ack).await?;

                                    tracing::info!(
                                        router = %router_name,
                                        partition = handoff.partition,
                                        "cutover complete, ack written"
                                    );
                                }
                                Ok(_) => {}
                                Err(e) => {
                                    tracing::error!(error = %e, "failed to parse handoff event");
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
