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
use crate::types::{
    HandoffPhase, HandoffState, PodDrainedAck, PodStatus, PodWarmedAck, RegisteredPod,
};
use crate::util;

/// Trait for the application-layer handoff handler on writer pods.
///
/// Implementations do the actual work of draining, warming, and releasing
/// partition ownership. Called by `PodHandle` in response to handoff phase
/// transitions it observes via etcd.
#[async_trait]
pub trait HandoffHandler: Send + Sync {
    /// Old owner: wait for all inflight request handlers for this partition to
    /// complete. Because the produce path awaits delivery before returning, this
    /// implies every write ever acked by this pod is durably in Kafka.
    ///
    /// Called when this pod is `old_owner` and handoff phase reaches `Freezing`.
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()>;

    /// New owner: populate the cache from Kafka up to current HWM.
    ///
    /// Called when this pod is `new_owner` and handoff phase reaches `Warming`.
    /// The HWM is guaranteed stable at this point — the old owner has drained
    /// and no router is producing for this partition.
    async fn warm_partition(&self, partition: u32) -> Result<()>;

    /// Old owner: release the partition from this pod's local state (drop cache,
    /// close consumers, etc.).
    ///
    /// Called when this pod is `old_owner` and handoff phase reaches `Complete`.
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

        // Phase 1: Normal operation. The unified handoff protocol makes the
        // handoff watch the sole source of ownership transitions — assignment
        // changes only ever happen atomically with a handoff Complete event,
        // so there's no need to watch assignments separately.
        //
        // The outer `select!` against the cancel token is what guarantees we
        // exit promptly even when `watch_handoff_loop` is parked inside a
        // `handle_handoff_event` call. The loop's own `select!` only checks
        // the cancel token between iterations; if a phase handler (e.g.
        // `warm_partition`) blocks indefinitely, the inner check is never
        // re-polled. Racing the cancel token at this level drops the
        // in-flight loop future via cancel-by-drop, unwinding any stuck
        // handler and letting the pod proceed to drain + lease revoke.
        let result = tokio::select! {
            r = self.watch_handoff_loop(cancel.clone()) => r,
            _ = cancel.cancelled() => Ok(()),
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
        let is_old_owner = handoff.old_owner.as_deref() == Some(pod.as_str());

        // Old owner: on Draining, drain inflight and write a DrainedAck.
        // The produce path awaits Kafka delivery before returning, so "no
        // inflight handlers" implies "every acked write is durable in Kafka."
        // The coordinator only advances Freezing → Draining once every
        // router has FreezeAcked, so by the time we observe Draining no
        // new request can flow from any router to this pod and the
        // inflight==0 check is meaningful.
        if is_old_owner && handoff.phase == HandoffPhase::Draining {
            tracing::info!(
                pod,
                partition = handoff.partition,
                "draining inflight for partition"
            );
            self.handler
                .drain_partition_inflight(handoff.partition)
                .await?;

            let ack = PodDrainedAck {
                pod_name: pod.clone(),
                partition: handoff.partition,
                acked_at: util::now_seconds(),
            };
            self.store.put_drained_ack(&ack).await?;

            tracing::info!(pod, partition = handoff.partition, "drained ack written");
        }

        // New owner: on Warming, populate cache from Kafka to current HWM,
        // then write a WarmedAck so the coordinator can advance to Complete.
        if handoff.new_owner == *pod && handoff.phase == HandoffPhase::Warming {
            tracing::info!(
                pod,
                partition = handoff.partition,
                "warming cache for partition"
            );
            self.handler.warm_partition(handoff.partition).await?;
            self.owned_partitions.lock().await.insert(handoff.partition);

            let ack = PodWarmedAck {
                pod_name: pod.clone(),
                partition: handoff.partition,
                acked_at: util::now_seconds(),
            };
            self.store.put_warmed_ack(&ack).await?;

            tracing::info!(pod, partition = handoff.partition, "warmed ack written");
        }

        // Old owner: release on Complete. Skipped when old_owner is None
        // (initial assignment) — there is nothing to release.
        if is_old_owner && handoff.phase == HandoffPhase::Complete {
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
}
