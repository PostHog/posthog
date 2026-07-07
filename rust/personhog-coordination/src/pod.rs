use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use etcd_client::{EventType, WatchStream};
use tokio::sync::{Mutex, Notify};
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use k8s_awareness::types::{ControllerKind, ControllerRef};
use k8s_awareness::{DepartureReason, K8sAwareness};

use crate::error::{Error, Result};
use crate::store::{self, PersonhogStore};
use crate::types::{
    HandoffPhase, HandoffState, PartitionAssignment, PodDrainedAck, PodStatus, PodWarmedAck,
    RegisteredPod,
};
use crate::util;

/// The state this pod should hold for one partition, derived purely from
/// the durable coordination state — the partition's assignment and any
/// in-flight handoff. `PodHandle::converge` drives local state to match,
/// so a pod whose memory has diverged from etcd (most notably after a
/// crash-restart inside its lease TTL, which preserves its registration
/// and assignments but wipes its cache and fences) is repaired by
/// re-deriving rather than by replaying remembered events.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DesiredState {
    /// This pod owns the partition and no handoff constrains it: cache
    /// warm, writes admitted. Also the old owner's state during Freezing
    /// (routers are still collecting the freeze quorum; writes keep
    /// flowing until every router has stashed).
    Serving,
    /// This pod is the old owner of a handoff past the freeze quorum:
    /// writes fenced, inflight drained. `ack` is true while the protocol
    /// is waiting on this pod's DrainedAck (phase Draining) and false once
    /// the ack has been consumed (phase Warming) — re-acking after the
    /// phase advanced would risk orphaning an ack past the coordinator's
    /// cleanup. The cache is deliberately not warmed here: a cold restart
    /// mid-handoff serves read errors until cutover (or until a
    /// cancellation converges back to Serving, which warms).
    Drained { ack: bool },
    /// This pod is the new owner of a handoff in Warming: populate the
    /// cache from Kafka and write a WarmedAck.
    Acquiring,
    /// This pod must not hold the partition: it isn't assigned to it, its
    /// outbound handoff completed, or it is a new owner whose handoff
    /// hasn't reached Warming (warming early would snapshot an HWM the old
    /// owner is still advancing).
    Released,
}

/// Pure derivation of a pod's desired state for a partition. The handoff,
/// when it involves this pod, takes precedence over the assignment: the
/// assignment names the *old* owner (or nobody) for the whole life of a
/// handoff and only flips to the new owner atomically at Complete.
fn desired_state(
    pod: &str,
    assignment: Option<&PartitionAssignment>,
    handoff: Option<&HandoffState>,
) -> DesiredState {
    if let Some(h) = handoff {
        if h.old_owner.as_deref() == Some(pod) {
            return match h.phase {
                HandoffPhase::Freezing => DesiredState::Serving,
                HandoffPhase::Draining => DesiredState::Drained { ack: true },
                HandoffPhase::Warming => DesiredState::Drained { ack: false },
                HandoffPhase::Complete => DesiredState::Released,
            };
        }
        if h.new_owner == pod {
            return match h.phase {
                HandoffPhase::Freezing | HandoffPhase::Draining => DesiredState::Released,
                HandoffPhase::Warming => DesiredState::Acquiring,
                // The assignment flips to this pod in the same txn that
                // writes Complete.
                HandoffPhase::Complete => DesiredState::Serving,
            };
        }
        // A handoff between two other pods constrains nothing for this
        // one; fall through to the assignment.
    }
    match assignment {
        Some(a) if a.owner == pod => DesiredState::Serving,
        _ => DesiredState::Released,
    }
}

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

    /// The handoff for a partition this pod still owns was cancelled before
    /// completing (e.g. the new owner died mid-warm and the coordinator
    /// deleted the record). The pod remains the owner and must resume
    /// normal service — in particular, re-admit any writes it fenced when
    /// it drained.
    ///
    /// Called when a handoff record is deleted while this pod still holds
    /// the partition (a delete after `Complete` is normal cleanup and does
    /// not trigger this).
    async fn resume_partition(&self, partition: u32) -> Result<()>;
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
    /// Partitions warmed by this process — local, dies with the process.
    /// `converge` consults it to decide whether a Serving/Acquiring
    /// partition still needs a warm, and `drain()` waits for it to empty.
    warmed_partitions: Mutex<HashSet<u32>>,
    /// Partitions this process has write-fenced via a drain — local,
    /// consulted so convergence to Serving only issues a resume when a
    /// fence actually exists.
    fenced_partitions: Mutex<HashSet<u32>>,
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
            warmed_partitions: Mutex::new(HashSet::new()),
            fenced_partitions: Mutex::new(HashSet::new()),
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
        let mut heartbeat_handle = {
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
        //
        // The heartbeat task is raced here too: the coordinator treats
        // lease expiry as pod death and hands this pod's partitions to
        // new owners, so a pod that outlives its lease is a zombie — it
        // would keep accepting writes for partitions the protocol has
        // already moved. Losing the lease therefore terminates the run
        // loop (self-fence) and the process restarts through the normal
        // lifecycle.
        let mut lease_lost = false;
        let result = tokio::select! {
            r = async {
                // Converge every partition this pod is involved in before
                // watching for new events. A pod that crash-restarts within
                // its lease TTL keeps its registration and assignments but
                // loses all in-memory state (cache, fences) — and because
                // nothing about etcd changed, no event will ever arrive to
                // repair the divergence. Re-deriving local state from the
                // durable state at startup closes that structurally: cold
                // assigned partitions re-warm, in-flight handoffs get their
                // drain/warm/ack, completed ones release. The watch is
                // anchored to the snapshot's revision, so an event landing
                // between the snapshot and the watch attaching is replayed
                // rather than lost.
                let snapshot_revision = self.reconcile_all().await?;
                let stream = self.store.watch_handoffs_from(snapshot_revision + 1).await?;
                self.watch_handoff_loop(stream, cancel.clone()).await
            } => r,
            r = &mut heartbeat_handle => {
                lease_lost = true;
                let err = match r {
                    Ok(Ok(())) => {
                        Error::invalid_state("lease keepalive exited unexpectedly".to_string())
                    }
                    Ok(Err(e)) => e,
                    Err(join_err) => {
                        Error::invalid_state(format!("keepalive task panicked: {join_err}"))
                    }
                };
                tracing::error!(
                    pod = %self.config.pod_name,
                    error = %err,
                    "lease keepalive failed; self-fencing"
                );
                Err(err)
            }
            _ = cancel.cancelled() => Ok(()),
        };

        // Phase 2: If cancelled externally (SIGTERM), drain gracefully.
        // Skipped on lease loss: the coordinator already considers this
        // pod dead and is reassigning its partitions via the dead-owner
        // path — a graceful drain would race it, and every status write
        // would fail against the expired lease anyway.
        if cancel.is_cancelled() && !lease_lost {
            if let Err(e) = self.drain(lease_id).await {
                tracing::warn!(pod = %self.config.pod_name, error = %e, "drain failed");
            }
        }

        // Cleanup: stop heartbeat and revoke lease. On lease loss the
        // heartbeat task has already exited (its handle must not be
        // awaited twice) and there is no lease left to revoke.
        if !lease_lost {
            heartbeat_cancel.cancel();
            drop(heartbeat_handle.await);
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

        if self.held_partition_count().await == 0 {
            tracing::info!(pod = %self.config.pod_name, "no partitions to drain");
            return Ok(());
        }

        // Keep converging during drain so partitions release as the
        // coordinator completes their handoffs. Reconcile first — a
        // Complete written while the main loop was winding down would
        // otherwise be missed — and anchor the fresh watch to the
        // snapshot's revision.
        let drain_cancel = CancellationToken::new();
        let snapshot_revision = self.reconcile_all().await?;
        let stream = self
            .store
            .watch_handoffs_from(snapshot_revision + 1)
            .await?;

        tokio::select! {
            r = self.watch_handoff_loop(stream, drain_cancel.clone()) => {
                r?;
            },
            _ = self.wait_for_drain() => {
                tracing::info!(pod = %self.config.pod_name, "all partitions drained successfully");
            },
            _ = tokio::time::sleep(self.config.drain_timeout) => {
                let remaining = self.held_partition_count().await;
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

    /// Number of partitions this process still holds state for — warmed
    /// or write-fenced. `drain()` waits for this to reach zero: a fenced
    /// partition's outbound handoff is still in flight, and the pod must
    /// stay alive to release it at Complete.
    async fn held_partition_count(&self) -> usize {
        let warmed = self.warmed_partitions.lock().await;
        let fenced = self.fenced_partitions.lock().await;
        warmed.union(&fenced).count()
    }

    /// Wait until all held partitions have been released via handoffs.
    /// Woken reactively by `drain_notify` each time a partition is released.
    async fn wait_for_drain(&self) {
        loop {
            if self.held_partition_count().await == 0 {
                return;
            }
            self.drain_notify.notified().await;
        }
    }

    /// Converge every partition this pod is involved in — assigned to it,
    /// or named in a handoff as old or new owner — from a consistent
    /// snapshot of the durable state. Returns the smaller of the two
    /// snapshot revisions so the caller can anchor the handoff watch: any
    /// change landing between the two reads (or between them and the watch
    /// attaching) is redelivered as an event and re-converged with fresh
    /// reads.
    async fn reconcile_all(&self) -> Result<i64> {
        let (assignments, rev_a) = self.store.list_assignments_with_revision().await?;
        let (handoffs, rev_h) = self.store.list_handoffs_with_revision().await?;
        let pod = &self.config.pod_name;

        let assignment_map: std::collections::HashMap<u32, &PartitionAssignment> =
            assignments.iter().map(|a| (a.partition, a)).collect();
        let handoff_map: std::collections::HashMap<u32, &HandoffState> =
            handoffs.iter().map(|h| (h.partition, h)).collect();

        let mut partitions: HashSet<u32> = HashSet::new();
        for a in &assignments {
            if a.owner == *pod {
                partitions.insert(a.partition);
            }
        }
        for h in &handoffs {
            if h.old_owner.as_deref() == Some(pod.as_str()) || h.new_owner == *pod {
                partitions.insert(h.partition);
            }
        }

        tracing::info!(
            pod,
            partitions = partitions.len(),
            "reconciling local state against durable state"
        );
        for partition in partitions {
            self.apply(
                partition,
                assignment_map.get(&partition).copied(),
                handoff_map.get(&partition).copied(),
            )
            .await?;
        }

        Ok(rev_a.min(rev_h))
    }

    /// Re-derive and apply the desired state for one partition from fresh
    /// point reads. Every watch event is just a signal to look again —
    /// convergence acts on observed durable state, never on remembered
    /// event payloads, so missed, reordered, or replayed events cannot
    /// corrupt local state.
    async fn converge(&self, partition: u32) -> Result<()> {
        let handoff = self.store.get_handoff(partition).await?;
        let assignment = self.store.get_assignment(partition).await?;
        self.apply(partition, assignment.as_ref(), handoff.as_ref())
            .await
    }

    /// Drive local state (cache warmth, write fence, acks, held set) to
    /// the desired state. Every transition is idempotent; callers are
    /// serialized (startup reconcile, then the single watch loop), so no
    /// two applications for the same partition ever interleave.
    async fn apply(
        &self,
        partition: u32,
        assignment: Option<&PartitionAssignment>,
        handoff: Option<&HandoffState>,
    ) -> Result<()> {
        let pod = &self.config.pod_name;
        let desired = desired_state(pod, assignment, handoff);

        match desired {
            DesiredState::Serving => {
                if !self.warmed_partitions.lock().await.contains(&partition) {
                    tracing::info!(pod, partition, "converging to Serving: warming");
                    self.handler.warm_partition(partition).await?;
                    self.warmed_partitions.lock().await.insert(partition);
                } else if self.fenced_partitions.lock().await.contains(&partition) {
                    tracing::info!(pod, partition, "converging to Serving: resuming writes");
                    self.handler.resume_partition(partition).await?;
                }
                self.fenced_partitions.lock().await.remove(&partition);
            }
            DesiredState::Drained { ack } => {
                // The coordinator only advances Freezing → Draining once
                // every router has FreezeAcked, so no new request can flow
                // from any router to this pod and the inflight==0 the drain
                // waits for is meaningful. The produce path awaits Kafka
                // delivery before returning, so "no inflight handlers"
                // implies "every acked write is durable in Kafka."
                if !self.fenced_partitions.lock().await.contains(&partition) {
                    tracing::info!(pod, partition, "converging to Drained: fencing + draining");
                }
                self.handler.drain_partition_inflight(partition).await?;
                self.fenced_partitions.lock().await.insert(partition);
                if ack {
                    let handoff = handoff.expect("Drained state only derives from a handoff");
                    self.store
                        .put_drained_ack(&PodDrainedAck {
                            pod_name: pod.clone(),
                            partition,
                            acked_at: util::now_seconds(),
                            handoff_id: handoff.handoff_id.clone(),
                        })
                        .await?;
                    tracing::info!(pod, partition, "drained ack written");
                }
            }
            DesiredState::Acquiring => {
                if !self.warmed_partitions.lock().await.contains(&partition) {
                    tracing::info!(pod, partition, "converging to Acquiring: warming");
                    self.handler.warm_partition(partition).await?;
                    self.warmed_partitions.lock().await.insert(partition);
                }
                self.fenced_partitions.lock().await.remove(&partition);
                let handoff = handoff.expect("Acquiring state only derives from a handoff");
                self.store
                    .put_warmed_ack(&PodWarmedAck {
                        pod_name: pod.clone(),
                        partition,
                        acked_at: util::now_seconds(),
                        handoff_id: handoff.handoff_id.clone(),
                    })
                    .await?;
                tracing::info!(pod, partition, "warmed ack written");
            }
            DesiredState::Released => {
                let was_warmed = self.warmed_partitions.lock().await.remove(&partition);
                let was_fenced = self.fenced_partitions.lock().await.remove(&partition);
                if was_warmed || was_fenced {
                    tracing::info!(pod, partition, "converging to Released: releasing");
                    self.handler.release_partition(partition).await?;
                    self.drain_notify.notify_one();
                }
            }
        }

        Ok(())
    }

    async fn watch_handoff_loop(
        &self,
        mut stream: WatchStream,
        cancel: CancellationToken,
    ) -> Result<()> {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("handoff watch stream ended".to_string()))?;
                    for event in resp.events() {
                        let partition = match event.event_type() {
                            EventType::Put => match parse_watch_value::<HandoffState>(event) {
                                Ok(handoff) => Some(handoff.partition),
                                Err(e) => {
                                    tracing::error!(pod = %self.config.pod_name, error = %e, "failed to parse handoff");
                                    None
                                }
                            },
                            EventType::Delete => event
                                .kv()
                                .and_then(|kv| std::str::from_utf8(kv.key()).ok())
                                .and_then(store::extract_partition_from_key),
                        };
                        if let Some(partition) = partition {
                            self.converge(partition).await?;
                        }
                    }
                }
            }
        }
    }
}
