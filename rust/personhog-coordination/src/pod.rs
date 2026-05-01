use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use etcd_client::EventType;
use tokio::sync::{Mutex, Notify};
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use k8s_awareness::types::{ControllerKind, ControllerRef};
use k8s_awareness::{DepartureReason, K8sAwareness};

use crate::error::{Error, Result};
use crate::store::PersonhogStore;
use crate::types::{HandoffPhase, HandoffState, PartitionAssignment, PodStatus, RegisteredPod};
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
    /// Pod-template-hash (Deployment) or controller-revision-hash (StatefulSet).
    /// Populated via K8s awareness before registration. Empty when K8s awareness is disabled.
    pub generation: String,
    /// The K8s controller (Deployment/StatefulSet) that owns this pod.
    /// Populated via K8s awareness before registration. None when K8s awareness is disabled.
    pub controller: Option<ControllerRef>,
    pub lease_ttl: i64,
    pub heartbeat_interval: Duration,
    /// How long to wait for partitions to drain before shutting down.
    /// Should be less than K8s terminationGracePeriodSeconds to allow
    /// time for lease revocation before SIGKILL.
    pub drain_timeout: Duration,
}

impl Default for PodConfig {
    fn default() -> Self {
        Self {
            pod_name: "writer-0".to_string(),
            generation: String::new(),
            controller: None,
            lease_ttl: 30,
            heartbeat_interval: Duration::from_secs(10),
            drain_timeout: Duration::from_secs(30),
        }
    }
}

pub struct PodHandle {
    store: Arc<PersonhogStore>,
    config: PodConfig,
    handler: Arc<dyn HandoffHandler>,
    /// Partitions this pod has warmed. Used to avoid re-warming on assignment watches.
    owned_partitions: Mutex<HashSet<u32>>,
    /// Signalled when a partition is released, waking `drain()` without polling.
    drain_notify: Notify,
    /// Optional K8s awareness for departure classification during shutdown.
    k8s_awareness: Option<Arc<K8sAwareness>>,
}

impl PodHandle {
    pub fn new(
        store: Arc<PersonhogStore>,
        config: PodConfig,
        handler: Arc<dyn HandoffHandler>,
        k8s_awareness: Option<Arc<K8sAwareness>>,
    ) -> Self {
        Self {
            store,
            config,
            handler,
            owned_partitions: Mutex::new(HashSet::new()),
            drain_notify: Notify::new(),
            k8s_awareness,
        }
    }

    /// Run the pod coordination loop. Blocks until cancelled.
    ///
    /// 1. Register with etcd (creates lease + key)
    /// 2. Start heartbeat loop
    /// 3. Watch for handoff and assignment events
    /// 4. On cancellation (SIGTERM): transition to Draining, wait for
    ///    partition handoffs to complete, then revoke lease and exit
    pub async fn run(&self, cancel: CancellationToken) -> Result<()> {
        let lease_id = self.store.grant_lease(self.config.lease_ttl).await?;
        self.register(lease_id).await?;

        tracing::info!(pod = %self.config.pod_name, "registered with etcd");

        // Heartbeat runs for the entire pod lifetime, including drain phase.
        // This keeps the lease alive so the coordinator sees a Draining pod
        // (not a crashed one with an expired lease).
        let heartbeat_cancel = CancellationToken::new();
        let heartbeat_handle = {
            let store = Arc::clone(&self.store);
            let interval = self.config.heartbeat_interval;
            let token = heartbeat_cancel.child_token();
            tokio::spawn(async move {
                util::run_lease_keepalive(store, lease_id, interval, token).await
            })
        };

        // Phase 1: Normal operation - watch handoffs and assignments until cancelled
        let result = tokio::select! {
            r = self.watch_handoff_loop(cancel.clone()) => r,
            r = self.watch_assignment_loop(cancel.clone()) => r,
        };

        // Phase 2: If cancelled externally (SIGTERM), drain gracefully
        if cancel.is_cancelled() {
            if let Err(e) = self.drain(lease_id).await {
                tracing::warn!(pod = %self.config.pod_name, error = %e, "drain failed");
            }
        }

        // Cleanup: stop heartbeat and revoke lease
        heartbeat_cancel.cancel();
        drop(heartbeat_handle.await);
        drop(self.store.revoke_lease(lease_id).await);

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
            controller: self.config.controller.clone(),
        };
        self.store.register_pod(&pod, lease_id).await
    }

    /// Classify the departure reason using K8s awareness, if available.
    async fn classify_departure(&self) -> DepartureReason {
        let (Some(k8s), Some(controller)) = (&self.k8s_awareness, &self.config.controller) else {
            return DepartureReason::Unknown;
        };

        k8s.classify_departure(controller, &self.config.generation)
            .await
    }

    /// Graceful drain: set status to Draining, then keep processing handoff
    /// events until all owned partitions have been released or timeout.
    ///
    /// The coordinator sees the Draining status, excludes this pod from
    /// active assignments, and creates handoffs for its partitions. This pod
    /// continues watching for handoff Complete events to release partitions.
    ///
    /// For StatefulSet rollouts, the same pod name comes back with a new
    /// revision, so we skip the drain and exit immediately (ShutdownNow).
    async fn drain(&self, lease_id: i64) -> Result<()> {
        let reason = self.classify_departure().await;

        // StatefulSet rollout: same pod name returns, no need to drain
        let is_statefulset_rollout = matches!(
            (&self.config.controller, reason),
            (Some(ref c), DepartureReason::Rollout) if c.kind == ControllerKind::StatefulSet
        );

        if is_statefulset_rollout {
            tracing::info!(
                pod = %self.config.pod_name,
                reason = %reason,
                "StatefulSet rollout detected, shutting down immediately"
            );
            return Ok(());
        }

        self.store
            .update_pod_status(&self.config.pod_name, PodStatus::Draining, lease_id)
            .await?;

        tracing::info!(
            pod = %self.config.pod_name,
            reason = %reason,
            "set status to Draining, waiting for partition handoffs"
        );

        if self.owned_partitions.lock().await.is_empty() {
            tracing::info!(pod = %self.config.pod_name, "no partitions to drain");
            return Ok(());
        }

        // Keep watching handoffs during drain so we can release partitions
        // when the coordinator completes them.
        let drain_cancel = CancellationToken::new();

        tokio::select! {
            r = self.watch_handoff_loop(drain_cancel.clone()) => {
                r?;
            },
            _ = self.wait_for_drain() => {
                tracing::info!(pod = %self.config.pod_name, "all partitions drained successfully");
            },
            _ = tokio::time::sleep(self.config.drain_timeout) => {
                let remaining = self.owned_partitions.lock().await.len();
                tracing::warn!(
                    pod = %self.config.pod_name,
                    remaining_partitions = remaining,
                    "drain timeout exceeded, shutting down"
                );
            }
        }

        drain_cancel.cancel();
        Ok(())
    }

    /// Wait until all owned partitions have been released via handoffs.
    /// Woken reactively by `drain_notify` each time a partition is released.
    async fn wait_for_drain(&self) {
        loop {
            if self.owned_partitions.lock().await.is_empty() {
                return;
            }
            self.drain_notify.notified().await;
        }
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
                            match parse_watch_value::<HandoffState>(event) {
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
            self.owned_partitions.lock().await.insert(handoff.partition);

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
            self.owned_partitions
                .lock()
                .await
                .remove(&handoff.partition);
            self.drain_notify.notify_one();
        }

        Ok(())
    }

    /// Watch for direct assignment changes. This handles the case where the
    /// coordinator assigns partitions without handoffs (e.g., initial assignment
    /// when the first pod registers).
    async fn watch_assignment_loop(&self, cancel: CancellationToken) -> Result<()> {
        // Load existing assignments that were created before this pod started.
        // The watch stream only delivers events after it's established, so
        // without this initial scan, pre-existing assignments would be missed.
        let existing = self.store.list_assignments().await?;
        for assignment in &existing {
            self.handle_assignment_event(assignment).await?;
        }

        let mut stream = self.store.watch_assignments().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("assignment watch stream ended".to_string()))?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            match parse_watch_value::<PartitionAssignment>(event) {
                                Ok(assignment) => {
                                    self.handle_assignment_event(&assignment).await?;
                                }
                                Err(e) => {
                                    tracing::error!(pod = %self.config.pod_name, error = %e, "failed to parse assignment");
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    async fn handle_assignment_event(&self, assignment: &PartitionAssignment) -> Result<()> {
        let pod = &self.config.pod_name;

        if assignment.owner != *pod {
            return Ok(());
        }

        // Skip if we already own this partition (warmed via handoff or prior assignment)
        if self
            .owned_partitions
            .lock()
            .await
            .contains(&assignment.partition)
        {
            return Ok(());
        }

        // Check if there's an active handoff for this partition — if so, the
        // handoff handler will take care of warming
        let handoffs = self.store.list_handoffs().await.unwrap_or_default();
        if handoffs.iter().any(|h| h.partition == assignment.partition) {
            return Ok(());
        }

        // Direct assignment without handoff — warm the partition
        tracing::info!(
            pod,
            partition = assignment.partition,
            "warming partition from direct assignment"
        );
        self.handler.warm_partition(assignment.partition).await?;
        self.owned_partitions
            .lock()
            .await
            .insert(assignment.partition);

        Ok(())
    }
}
