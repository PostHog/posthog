use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use etcd_client::EventType;
use tokio_util::sync::CancellationToken;

use crate::error::{Error, Result};
use crate::store::{self, PersonhogStore};
use crate::types::{HandoffPhase, HandoffState, PodStatus, RegisteredPod};
use crate::util;

/// Trait for the application-layer handoff handler on writer pods.
///
/// Implementations do the actual work of warming caches and releasing resources.
/// This is the primary extension point: writer pods implement this trait with
/// real Kafka consumption and cache management.
#[async_trait]
pub trait HandoffHandler: Send + Sync {
    /// Warm the cache for a partition (e.g., consume from Kafka until caught up).
    async fn warm_partition(&self, partition: u32) -> Result<()>;

    /// Release a partition (clear cache, unassign Kafka consumer, etc.).
    async fn release_partition(&self, partition: u32) -> Result<()>;
}

#[derive(Debug, Clone)]
pub struct PodConfig {
    pub pod_name: String,
    pub generation: String,
    pub lease_ttl: i64,
    pub heartbeat_interval: Duration,
}

impl Default for PodConfig {
    fn default() -> Self {
        Self {
            pod_name: "writer-0".to_string(),
            generation: "blue".to_string(),
            lease_ttl: 30,
            heartbeat_interval: Duration::from_secs(10),
        }
    }
}

pub struct PodHandle {
    store: Arc<PersonhogStore>,
    config: PodConfig,
    handler: Arc<dyn HandoffHandler>,
}

impl PodHandle {
    pub fn new(
        store: Arc<PersonhogStore>,
        config: PodConfig,
        handler: Arc<dyn HandoffHandler>,
    ) -> Self {
        Self {
            store,
            config,
            handler,
        }
    }

    /// Run the pod coordination loop. Blocks until cancelled.
    ///
    /// 1. Register with etcd (creates lease + key)
    /// 2. Start heartbeat loop
    /// 3. Watch for handoff events
    pub async fn run(&self, cancel: CancellationToken) -> Result<()> {
        let lease_id = self.store.grant_lease(self.config.lease_ttl).await?;
        self.register(lease_id).await?;

        tracing::info!(pod = %self.config.pod_name, "registered with etcd");

        let result = self.run_loops(lease_id, cancel.clone()).await;

        // Best-effort unregister on shutdown
        if !cancel.is_cancelled() {
            drop(self.store.revoke_lease(lease_id).await);
        }

        result
    }

    async fn register(&self, lease_id: i64) -> Result<()> {
        let now = util::now_seconds();
        let pod = RegisteredPod {
            pod_name: self.config.pod_name.clone(),
            generation: self.config.generation.clone(),
            status: PodStatus::Ready,
            registered_at: now,
            last_heartbeat: now,
        };
        self.store.register_pod(&pod, lease_id).await
    }

    async fn run_loops(&self, lease_id: i64, cancel: CancellationToken) -> Result<()> {
        let heartbeat_cancel = cancel.child_token();
        let heartbeat_handle = {
            let store = Arc::clone(&self.store);
            let interval = self.config.heartbeat_interval;
            let token = heartbeat_cancel.clone();
            tokio::spawn(async move {
                util::run_lease_keepalive(store, lease_id, interval, token).await
            })
        };

        let handoff_result = self.watch_handoff_loop(cancel.clone()).await;

        heartbeat_cancel.cancel();
        drop(heartbeat_handle.await);

        handoff_result
    }

    async fn watch_handoff_loop(&self, cancel: CancellationToken) -> Result<()> {
        let mut stream = self.store.watch_handoffs().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("handoff watch stream ended".to_string()))?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            match store::parse_watch_value::<HandoffState>(event) {
                                Ok(handoff) => {
                                    self.handle_handoff_event(&handoff).await?;
                                }
                                Err(e) => {
                                    tracing::error!(pod = %self.config.pod_name, error = %e, "failed to parse handoff");
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    async fn handle_handoff_event(&self, handoff: &HandoffState) -> Result<()> {
        let pod = &self.config.pod_name;

        // New owner: warm cache when handoff starts
        if handoff.new_owner == *pod && handoff.phase == HandoffPhase::Warming {
            tracing::info!(
                pod,
                partition = handoff.partition,
                "warming cache for partition"
            );
            self.handler.warm_partition(handoff.partition).await?;

            // Signal ready — routers will now begin cutover
            let mut updated = handoff.clone();
            updated.phase = HandoffPhase::Ready;
            self.store.put_handoff(&updated).await?;

            tracing::info!(pod, partition = handoff.partition, "reported ready");
        }

        // Old owner: release on complete (all routers have cut over)
        if handoff.old_owner == *pod && handoff.phase == HandoffPhase::Complete {
            tracing::info!(pod, partition = handoff.partition, "releasing partition");
            self.handler.release_partition(handoff.partition).await?;
        }

        Ok(())
    }
}
