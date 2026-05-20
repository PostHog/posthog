use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use etcd_client::EventType;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;

use crate::error::{Error, Result};
use crate::store::{self, PersonhogStore};
use crate::types::{HandoffPhase, HandoffState, RegisteredRouter, RouterFreezeAck};
use crate::util;

/// Trait for the router-side stash handler. Implementations are responsible
/// for holding writes to a partition while a handoff is in progress, then
/// draining the stash to the new owner once the handoff completes.
#[async_trait]
pub trait StashHandler: Send + Sync {
    /// Begin stashing writes for the partition. Must be idempotent — may be
    /// called more than once for the same partition across non-terminal
    /// phase transitions (`Freezing` → `Draining` → `Warming`) and on
    /// watch reconnects.
    async fn begin_stash(&self, partition: u32, new_owner: &str) -> Result<()>;

    /// Drain stashed writes to the given target and resume normal routing.
    async fn drain_stash(&self, partition: u32, target: &str) -> Result<()>;
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

/// Routing table that watches etcd handoffs to keep its
/// partition-to-owner map in sync.
///
/// Ongoing routing changes are driven entirely by handoff Complete events —
/// the atomic `complete_handoff` txn writes both `phase=Complete` and the
/// new `PartitionAssignment`, and we update the local table inside the
/// handoff watch so both sides stay consistent without racing against a
/// separate assignment watch.
///
/// Initial state is loaded once at startup via `load_initial` from
/// `list_assignments`. After that, only handoff completion events mutate
/// the table. Any out-of-band write to `assignments/{partition}` is
/// invisible to routers by design; see `PersonhogStore::complete_handoff`
/// for the wider invariant.
///
/// During non-terminal phases (`Freezing`, `Draining`, `Warming`) the
/// routing table calls `StashHandler::begin_stash` and writes a
/// `RouterFreezeAck` so the coordinator can collect freeze quorum. At
/// `Complete` the table flips to the new owner and `drain_stash` flushes
/// any buffered requests through the standard forwarding path.
pub struct RoutingTable {
    store: Arc<PersonhogStore>,
    config: RoutingTableConfig,
    table: Arc<RwLock<HashMap<u32, String>>>,
}

impl RoutingTable {
    pub fn new(store: Arc<PersonhogStore>, config: RoutingTableConfig) -> Self {
        Self {
            store,
            config,
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
    /// then watches the handoffs keyspace. Blocks until cancelled. Routing
    /// changes flow exclusively through handoff Complete events; there is
    /// no separate assignment watch.
    ///
    /// The `handler` implements stashing and drain. It's invoked on handoff
    /// phase transitions: `begin_stash` at Freezing, `drain_stash` at Complete.
    /// Accepting it here (rather than in the constructor) lets callers build
    /// the handler after the routing table, avoiding circular-dependency
    /// workarounds like `OnceCell`.
    pub async fn run(
        &self,
        cancel: CancellationToken,
        handler: Arc<dyn StashHandler>,
    ) -> Result<()> {
        // Register this router so the coordinator can count it for ack quorum
        let lease_id = self.store.grant_lease(self.config.lease_ttl).await?;
        self.register_router(lease_id).await?;

        self.load_initial(&handler).await?;

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
            let handler = Arc::clone(&handler);
            let router_name = self.config.router_name.clone();
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_handoffs_loop(store, table, handler, router_name, token).await
            });
        }

        let result = tokio::select! {
            _ = cancel.cancelled() => Ok(()),
            Some(result) = tasks.join_next() => {
                result.map_err(|e| Error::invalid_state(format!("task panicked: {e}")))?
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

    async fn load_initial(&self, handler: &Arc<dyn StashHandler>) -> Result<()> {
        let assignments = self.store.list_assignments().await?;
        let mut table = self.table.write().await;
        for a in assignments {
            table.insert(a.partition, a.owner);
        }
        tracing::info!(count = table.len(), "loaded initial routing table");
        drop(table);

        // Catch up on any in-progress handoffs. A late-joining router that
        // observes a non-terminal handoff needs to begin stashing — and if
        // we're still in Freezing, also write a FreezeAck so the
        // coordinator's quorum can progress. Handoffs already at Complete
        // arrive as a normal Put event through the watch loop below.
        let handoffs = self.store.list_handoffs().await?;
        for handoff in handoffs {
            if matches!(
                handoff.phase,
                HandoffPhase::Freezing | HandoffPhase::Draining | HandoffPhase::Warming
            ) {
                tracing::info!(
                    router = %self.config.router_name,
                    partition = handoff.partition,
                    old_owner = ?handoff.old_owner,
                    new_owner = %handoff.new_owner,
                    phase = ?handoff.phase,
                    "catching up on in-progress handoff: begin stash"
                );

                handler
                    .begin_stash(handoff.partition, &handoff.new_owner)
                    .await?;

                // Only write a FreezeAck while still in Freezing — once
                // the coordinator advanced past Freezing, the freeze
                // quorum has been collected and a late ack would be
                // either redundant or, worse, mistakenly counted toward
                // a future handoff for the same partition.
                if handoff.phase == HandoffPhase::Freezing {
                    let ack = RouterFreezeAck {
                        router_name: self.config.router_name.clone(),
                        partition: handoff.partition,
                        acked_at: util::now_seconds(),
                    };
                    self.store.put_freeze_ack(&ack).await?;
                }
            }
        }

        Ok(())
    }

    async fn watch_handoffs_loop(
        store: Arc<PersonhogStore>,
        table: Arc<RwLock<HashMap<u32, String>>>,
        handler: Arc<dyn StashHandler>,
        router_name: String,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_handoffs().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("handoff watch stream ended".to_string()))?;
                    for event in resp.events() {
                        match event.event_type() {
                            EventType::Put => {
                                Self::handle_handoff_put(
                                    event,
                                    store.as_ref(),
                                    &table,
                                    handler.as_ref(),
                                    &router_name,
                                ).await?;
                            }
                            EventType::Delete => {
                                // Handoff cancelled (typically by
                                // cleanup_stale_handoffs). Drain any stash
                                // back to whoever the routing table still
                                // points at — during Freezing/Warming the
                                // assignment never moved, so that's the old
                                // owner (or an initial target with no prior
                                // assignment yet).
                                let Some(kv) = event.kv() else { continue };
                                let key = std::str::from_utf8(kv.key()).unwrap_or("");
                                let Some(partition) = store::extract_partition_from_key(key) else {
                                    continue
                                };
                                let target = table.read().await.get(&partition).cloned();
                                match target {
                                    Some(owner) => {
                                        tracing::warn!(
                                            router = %router_name,
                                            partition,
                                            owner = %owner,
                                            "handoff cancelled, draining stash back to current owner"
                                        );
                                        handler.drain_stash(partition, &owner).await?;
                                    }
                                    None => {
                                        tracing::warn!(
                                            router = %router_name,
                                            partition,
                                            "handoff cancelled with no current assignment; stash left intact"
                                        );
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    async fn handle_handoff_put(
        event: &etcd_client::Event,
        store: &PersonhogStore,
        table: &Arc<RwLock<HashMap<u32, String>>>,
        handler: &dyn StashHandler,
        router_name: &str,
    ) -> Result<()> {
        let handoff: HandoffState = match parse_watch_value(event) {
            Ok(h) => h,
            Err(e) => {
                tracing::error!(error = %e, "failed to parse handoff event");
                return Ok(());
            }
        };

        match handoff.phase {
            HandoffPhase::Freezing | HandoffPhase::Draining | HandoffPhase::Warming => {
                tracing::info!(
                    router = %router_name,
                    partition = handoff.partition,
                    new_owner = %handoff.new_owner,
                    phase = ?handoff.phase,
                    "beginning stash"
                );
                handler
                    .begin_stash(handoff.partition, &handoff.new_owner)
                    .await?;

                // Only write a FreezeAck in Freezing — routers can arrive
                // late, observe a later phase, and must not re-ack a
                // quorum that has already cleared.
                if handoff.phase == HandoffPhase::Freezing {
                    let ack = RouterFreezeAck {
                        router_name: router_name.to_string(),
                        partition: handoff.partition,
                        acked_at: util::now_seconds(),
                    };
                    store.put_freeze_ack(&ack).await?;
                }
            }
            HandoffPhase::Complete => {
                // Pre-update the routing table before draining so that any
                // new request arriving between drain and the independent
                // assignment-watch dispatch routes to the new owner rather
                // than to the old owner (which has already released). The
                // assignment watch will later re-set the same value
                // idempotently.
                table
                    .write()
                    .await
                    .insert(handoff.partition, handoff.new_owner.clone());

                tracing::info!(
                    router = %router_name,
                    partition = handoff.partition,
                    new_owner = %handoff.new_owner,
                    "updated routing table and draining stash to new owner"
                );
                handler
                    .drain_stash(handoff.partition, &handoff.new_owner)
                    .await?;
            }
        }
        Ok(())
    }
}
