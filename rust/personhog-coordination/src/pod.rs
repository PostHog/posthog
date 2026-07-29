use std::collections::{HashMap, HashSet};
use std::str::from_utf8;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use etcd_client::{EventType, WatchStream};
use futures::future::BoxFuture;
use futures::stream::{FuturesUnordered, StreamExt};
use metrics::{counter, gauge, histogram};
use tokio::sync::{Mutex, Notify, Semaphore, SemaphorePermit};
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
/// Public because the stateright model (`personhog-stateright`) drives
/// its pod transitions through this exact function — the model checks
/// the code production runs, so the pod state machine cannot drift from
/// its verified form.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DesiredState {
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
pub fn desired_state(
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
    /// How often the watch loop re-derives the involved-partition set
    /// from a fresh snapshot, independent of events — the same truth
    /// path the router's reconcile pass provides. Runs as an arm of the
    /// watch loop; each pass re-dispatches every involved partition
    /// through the same single-flight convergence lanes the event path
    /// uses.
    pub reconcile_interval: Duration,
    /// How many consecutive reconcile failures to tolerate before
    /// failing the run. Same reasoning as the router's budget: a failed
    /// pass only means staleness equal to one tick, brief etcd blips
    /// must not restart the fleet, and sustained outage self-fences
    /// through the lease keepalive.
    pub reconcile_failure_budget: u32,
    /// `host:port` where this pod's gRPC server is reachable; registered
    /// so routers can dial the pod through the routing table.
    pub advertise_address: Option<String>,
    /// Maximum number of partition warms this pod runs concurrently.
    /// Warming several partitions at once keeps a deploy-burst of
    /// inbound handoffs from queueing each warm behind the last; the
    /// bound keeps a cold restart from opening one Kafka replay per
    /// assigned partition all at once. Only warms queue on this —
    /// drains, releases, and acks are never held behind warm pressure.
    pub warm_concurrency: usize,
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
            reconcile_interval: Duration::from_secs(5),
            reconcile_failure_budget: 12,
            advertise_address: None,
            warm_concurrency: 4,
        }
    }
}

/// What a partition's warm was installed for. A warm is only as fresh as
/// the moment it replayed the changelog; `converge` records why each one
/// was installed so a later Acquiring can tell a warm it may honor from
/// one left over from an earlier era.
#[derive(Debug, Clone, PartialEq, Eq)]
enum WarmProvenance {
    /// Warmed as (or on the way back to being) the serving owner: a
    /// process restart, or the returning old owner of an in-flight
    /// handoff. Current at install time and kept current by the pod's
    /// own accepted writes for as long as it remains the owner.
    Serving,
    /// Warmed for one specific handoff's Warming phase, identified by
    /// its id.
    Handoff(String),
}

pub struct PodHandle {
    store: Arc<PersonhogStore>,
    config: PodConfig,
    handler: Arc<dyn HandoffHandler>,
    /// Partitions warmed by this process — local, dies with the process —
    /// each with the provenance of its warm. `converge` consults it to
    /// decide whether a Serving/Acquiring partition still needs a warm,
    /// and `drain()` waits for it to empty.
    warmed_partitions: Mutex<HashMap<u32, WarmProvenance>>,
    /// Partitions this process has write-fenced via a drain — local,
    /// consulted so convergence to Serving only issues a resume when a
    /// fence actually exists.
    fenced_partitions: Mutex<HashSet<u32>>,
    /// Signalled when a partition is released, waking `drain()` without polling.
    drain_notify: Notify,
    /// Bounds concurrent `warm_partition` calls to `warm_concurrency`.
    warm_slots: Semaphore,
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
        let warm_slots = Semaphore::new(config.warm_concurrency);
        Self {
            store,
            config,
            handler,
            warmed_partitions: Mutex::new(HashMap::new()),
            fenced_partitions: Mutex::new(HashSet::new()),
            drain_notify: Notify::new(),
            warm_slots,
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
        // The outer `select!` against the cancel token is what guarantees a
        // prompt exit: dropping the loop future also drops every in-flight
        // convergence it is driving, so even a phase handler (e.g.
        // `warm_partition`) that blocks indefinitely cannot hold the pod
        // back from proceeding to drain + lease revoke.
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
                // Seed the loop with every partition this pod is involved
                // in before watching for new events. A pod that
                // crash-restarts within its lease TTL keeps its
                // registration and assignments but loses all in-memory
                // state (cache, fences) — and because nothing about etcd
                // changed, no event will ever arrive to repair the
                // divergence. Re-deriving local state from the durable
                // state at startup closes that structurally: cold assigned
                // partitions re-warm, in-flight handoffs get their
                // drain/warm/ack, completed ones release. The watch is
                // anchored to the snapshot's revision, so an event landing
                // between the snapshot and the watch attaching is replayed
                // rather than lost.
                let (initial, snapshot_revision) = self.involved_partitions().await?;
                let stream = self.store.watch_handoffs_from(snapshot_revision + 1).await?;
                self.watch_handoff_loop(stream, cancel.clone(), initial).await
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
            advertise_address: self.config.advertise_address.clone(),
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
        let (initial, snapshot_revision) = self.involved_partitions().await?;
        let stream = self
            .store
            .watch_handoffs_from(snapshot_revision + 1)
            .await?;

        tokio::select! {
            r = self.watch_handoff_loop(stream, drain_cancel.clone(), initial) => {
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
        warmed
            .keys()
            .chain(fenced.iter())
            .collect::<HashSet<_>>()
            .len()
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

    /// Derive every partition this pod is involved in — assigned to it,
    /// named in a handoff as old or new owner, or still held locally —
    /// from a consistent snapshot of the durable state. Returns the set
    /// alongside the smaller of the two snapshot revisions so the caller
    /// can anchor the handoff watch: any change landing between the two
    /// reads (or between them and the watch attaching) is redelivered as
    /// an event and re-converged with fresh reads.
    async fn involved_partitions(&self) -> Result<(HashSet<u32>, i64)> {
        let (assignments, rev_a) = self.store.list_assignments_with_revision().await?;
        let (handoffs, rev_h) = self.store.list_handoffs_with_revision().await?;
        let pod = &self.config.pod_name;

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
        // Locally-held partitions the durable state no longer involves
        // this pod in still need convergence — that is how a warm or
        // fence left over from a departed ownership gets released when
        // the Complete event that should have done it was missed.
        partitions.extend(self.warmed_partitions.lock().await.keys().copied());
        partitions.extend(self.fenced_partitions.lock().await.iter().copied());

        tracing::info!(
            pod,
            partitions = partitions.len(),
            "reconciling local state against durable state"
        );

        Ok((partitions, rev_a.min(rev_h)))
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

    /// Bound on concurrent cache warms. Only the two warm sites in
    /// `apply` queue here; everything else a convergence does (fence,
    /// drain, release, ack) must stay prompt regardless of warm pressure.
    async fn acquire_warm_slot(&self) -> Result<SemaphorePermit<'_>> {
        self.warm_slots
            .acquire()
            .await
            .map_err(|_| Error::invalid_state("warm semaphore closed".to_string()))
    }

    /// Drive local state (cache warmth, write fence, acks, held set) to
    /// the desired state. Every transition is idempotent; the watch loop
    /// runs at most one convergence per partition at a time, so no two
    /// applications for the same partition ever interleave — applications
    /// for different partitions may run concurrently.
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
                if !self.warmed_partitions.lock().await.contains_key(&partition) {
                    tracing::info!(pod, partition, "converging to Serving: warming");
                    let _warm_slot = self.acquire_warm_slot().await?;
                    let start = Instant::now();
                    self.handler.warm_partition(partition).await?;
                    histogram!("personhog_coordination_partition_warm_ms", "trigger" => "restart")
                        .record(start.elapsed().as_secs_f64() * 1000.0);
                    self.warmed_partitions
                        .lock()
                        .await
                        .insert(partition, WarmProvenance::Serving);
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
                let newly_fencing = !self.fenced_partitions.lock().await.contains(&partition);
                if newly_fencing {
                    tracing::info!(pod, partition, "converging to Drained: fencing + draining");
                }
                let start = Instant::now();
                self.handler.drain_partition_inflight(partition).await?;
                if newly_fencing {
                    // Only the first convergence does a real drain wait;
                    // later re-convergences are no-ops that would bury the
                    // signal in near-zero samples.
                    histogram!("personhog_coordination_partition_drain_ms")
                        .record(start.elapsed().as_secs_f64() * 1000.0);
                }
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
                let handoff = handoff.expect("Acquiring state only derives from a handoff");
                // Only a warm installed for *this* handoff satisfies its
                // warming. One left over from an earlier era — the pod
                // was this partition's owner or warming target before,
                // ownership moved away, and the intervening Released
                // convergence never ran — can hold values that predate
                // writes the changelog accepted since. A fresh warm
                // replays only from the writer's committed offset, so a
                // stale cache below that offset would keep hitting;
                // release first and rebuild from clean.
                let valid = self.warmed_partitions.lock().await.get(&partition).is_some_and(
                    |provenance| {
                        matches!(provenance, WarmProvenance::Handoff(id) if *id == handoff.handoff_id)
                    },
                );
                if !valid {
                    if self
                        .warmed_partitions
                        .lock()
                        .await
                        .remove(&partition)
                        .is_some()
                    {
                        tracing::info!(
                            pod,
                            partition,
                            "converging to Acquiring: releasing a warm from an earlier era"
                        );
                        self.handler.release_partition(partition).await?;
                    }
                    tracing::info!(pod, partition, "converging to Acquiring: warming");
                    let _warm_slot = self.acquire_warm_slot().await?;
                    let start = Instant::now();
                    self.handler.warm_partition(partition).await?;
                    histogram!("personhog_coordination_partition_warm_ms", "trigger" => "handoff")
                        .record(start.elapsed().as_secs_f64() * 1000.0);
                    self.warmed_partitions.lock().await.insert(
                        partition,
                        WarmProvenance::Handoff(handoff.handoff_id.clone()),
                    );
                }
                self.fenced_partitions.lock().await.remove(&partition);
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
                let was_warmed = self
                    .warmed_partitions
                    .lock()
                    .await
                    .remove(&partition)
                    .is_some();
                let was_fenced = self.fenced_partitions.lock().await.remove(&partition);
                if was_warmed || was_fenced {
                    tracing::info!(pod, partition, "converging to Released: releasing");
                    self.handler.release_partition(partition).await?;
                    counter!("personhog_coordination_partition_releases_total").increment(1);
                    self.drain_notify.notify_one();
                }
            }
        }

        gauge!("personhog_coordination_partitions_held")
            .set(self.held_partition_count().await as f64);

        Ok(())
    }

    async fn watch_handoff_loop(
        &self,
        mut stream: WatchStream,
        cancel: CancellationToken,
        initial: HashSet<u32>,
    ) -> Result<()> {
        // The truth path: periodically re-derive the involved-partition
        // set from a fresh snapshot and re-dispatch each member,
        // repairing whatever the event path failed to deliver. First
        // pass one interval out — the caller has just seeded `initial`
        // from the same derivation.
        let mut reconcile_tick = tokio::time::interval_at(
            tokio::time::Instant::now() + self.config.reconcile_interval,
            self.config.reconcile_interval,
        );

        // Convergence is single-flight per partition: at most one
        // `converge` future per partition lives in `lanes` at a time,
        // preserving the no-interleaving guarantee `apply` relies on,
        // while different partitions converge concurrently — a deploy
        // moving several partitions onto this pod warms them in
        // parallel instead of queueing each behind the last. A signal
        // arriving for a partition already converging parks in
        // `pending`; `converge` reads fresh state, so one re-run
        // absorbs any number of coalesced signals. Dropping this loop
        // future drops every in-flight convergence with it, so cancel
        // semantics are unchanged from converging inline.
        let mut lanes: FuturesUnordered<BoxFuture<'_, (u32, Trigger, Result<()>)>> =
            FuturesUnordered::new();
        let mut in_flight: HashSet<u32> = HashSet::new();
        let mut pending: HashMap<u32, Trigger> = HashMap::new();

        fn dispatch<'s>(
            handle: &'s PodHandle,
            partition: u32,
            trigger: Trigger,
            in_flight: &mut HashSet<u32>,
            pending: &mut HashMap<u32, Trigger>,
            lanes: &mut FuturesUnordered<BoxFuture<'s, (u32, Trigger, Result<()>)>>,
        ) {
            if in_flight.contains(&partition) {
                // Coalesce, keeping the stricter error disposition: a
                // fatal Event request must not be downgraded by a later
                // budgeted Reconcile one.
                let entry = pending.entry(partition).or_insert(trigger);
                if trigger == Trigger::Event {
                    *entry = Trigger::Event;
                }
                return;
            }
            in_flight.insert(partition);
            lanes.push(Box::pin(async move {
                (partition, trigger, handle.converge(partition).await)
            }));
        }

        for partition in initial {
            // Seed convergence carries Event severity: a pod that cannot
            // establish its local state at loop start must not serve.
            dispatch(
                self,
                partition,
                Trigger::Event,
                &mut in_flight,
                &mut pending,
                &mut lanes,
            );
        }

        // Reconcile health is judged per tick window, keeping the budget
        // at the pass granularity it was sized for: a window where any
        // reconcile-triggered convergence failed — or whose own
        // durable-state snapshot failed — counts exactly one failure, so
        // a single partition persistently failing (a bad warm, say)
        // still exhausts the budget even while its neighbors converge
        // fine, while one blip failing several things at once cannot
        // burn the budget faster than real time. A window of only
        // successes resets the count; a window with no completed
        // reconcile convergence at all (one still in flight across the
        // tick) is neutral.
        let mut consecutive_reconcile_failures: u32 = 0;
        let mut window_err: Option<Error> = None;
        let mut window_ok = false;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = reconcile_tick.tick() => {
                    // One budget count per tick at most, no matter how
                    // many things failed inside its window: the budget is
                    // sized in passes, and a single blip failing both a
                    // convergence and the following snapshot is one
                    // failed pass, not two.
                    let mut tick_err: Option<Error> = window_err.take();
                    if tick_err.is_none() && window_ok {
                        consecutive_reconcile_failures = 0;
                    }
                    window_ok = false;

                    // List failures are tolerated for the same reason as
                    // the router's reconcile arm: a failed pass leaves
                    // the pod as stale as one tick ago and the next
                    // success fully compensates, so a brief etcd blip
                    // must not take the data plane down with it. The
                    // budget bounds the reads-failing-while-lease-healthy
                    // mode.
                    match self.involved_partitions().await {
                        Ok((partitions, _)) => {
                            for partition in partitions {
                                dispatch(
                                    self,
                                    partition,
                                    Trigger::Reconcile,
                                    &mut in_flight,
                                    &mut pending,
                                    &mut lanes,
                                );
                            }
                        }
                        Err(e) => {
                            if tick_err.is_none() {
                                tick_err = Some(e);
                            } else {
                                tracing::warn!(
                                    pod = %self.config.pod_name,
                                    error = %e,
                                    "durable-state snapshot failed in an already-failed window"
                                );
                            }
                        }
                    }

                    if let Some(e) = tick_err {
                        consecutive_reconcile_failures += 1;
                        counter!(
                            "personhog_coordination_reconcile_failures_total",
                            "component" => "pod"
                        )
                        .increment(1);
                        tracing::warn!(
                            pod = %self.config.pod_name,
                            error = %e,
                            consecutive = consecutive_reconcile_failures,
                            budget = self.config.reconcile_failure_budget,
                            "pod reconcile failed; continuing on last-known state"
                        );
                        if consecutive_reconcile_failures >= self.config.reconcile_failure_budget {
                            return Err(e);
                        }
                    }
                }
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
                                .and_then(|kv| from_utf8(kv.key()).ok())
                                .and_then(store::extract_partition_from_key),
                        };
                        if let Some(partition) = partition {
                            dispatch(
                                self,
                                partition,
                                Trigger::Event,
                                &mut in_flight,
                                &mut pending,
                                &mut lanes,
                            );
                        }
                    }
                }
                Some((partition, trigger, result)) = lanes.next(), if !lanes.is_empty() => {
                    in_flight.remove(&partition);
                    match result {
                        Ok(()) => {
                            if trigger == Trigger::Reconcile {
                                window_ok = true;
                            }
                        }
                        Err(e) => match trigger {
                            // The pod was told about a specific durable
                            // transition and cannot honor it; serving on
                            // regardless would hold the handoff hostage
                            // with no signal to the coordinator.
                            Trigger::Event => return Err(e),
                            Trigger::Reconcile => {
                                tracing::warn!(
                                    pod = %self.config.pod_name,
                                    partition,
                                    error = %e,
                                    "reconcile-triggered convergence failed"
                                );
                                window_err = Some(e);
                            }
                        },
                    }
                    if let Some(next) = pending.remove(&partition) {
                        dispatch(self, partition, next, &mut in_flight, &mut pending, &mut lanes);
                    }
                }
            }
        }
    }
}

/// Why a convergence was dispatched — decides what its failure means.
/// Event-driven convergence (including the seed at loop start) failing is
/// fatal to the run: the pod cannot honor a specific durable transition
/// it was told about. Reconcile-tick convergence failing is tolerated
/// under the reconcile failure budget: the pod is merely as stale as one
/// tick, and the next pass compensates.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Trigger {
    Event,
    Reconcile,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::AssignmentStatus;

    const POD: &str = "pod-self";
    const OTHER: &str = "pod-other";
    const THIRD: &str = "pod-third";

    fn assignment(owner: &str) -> PartitionAssignment {
        PartitionAssignment {
            partition: 1,
            owner: owner.to_string(),
            advertise_address: None,
            status: AssignmentStatus::Active,
        }
    }

    fn handoff(old_owner: Option<&str>, new_owner: &str, phase: HandoffPhase) -> HandoffState {
        HandoffState {
            partition: 1,
            old_owner: old_owner.map(str::to_string),
            new_owner: new_owner.to_string(),
            phase,
            started_at: 0,
            handoff_id: "h-test".to_string(),
            freeze_quorum: None,
            created_at_ms: 0,
            phase_entered_at_ms: 0,
            new_owner_address: None,
        }
    }

    #[test]
    fn desired_state_covers_the_full_role_phase_matrix() {
        use DesiredState::*;
        use HandoffPhase::*;

        // (case, assignment, handoff, expected). Assignments mirror what
        // the protocol would hold at that point: they name the old owner
        // (or nobody) until Complete flips them to the new owner.
        let cases: Vec<(
            &str,
            Option<PartitionAssignment>,
            Option<HandoffState>,
            DesiredState,
        )> = vec![
            (
                "old owner serves through Freezing",
                Some(assignment(POD)),
                Some(handoff(Some(POD), OTHER, Freezing)),
                Serving,
            ),
            (
                "old owner drains and acks in Draining",
                Some(assignment(POD)),
                Some(handoff(Some(POD), OTHER, Draining)),
                Drained { ack: true },
            ),
            (
                "old owner stays drained without re-acking in Warming",
                Some(assignment(POD)),
                Some(handoff(Some(POD), OTHER, Warming)),
                Drained { ack: false },
            ),
            (
                "old owner releases at Complete",
                Some(assignment(OTHER)),
                Some(handoff(Some(POD), OTHER, Complete)),
                Released,
            ),
            (
                "new owner must not hold the partition in Freezing",
                Some(assignment(OTHER)),
                Some(handoff(Some(OTHER), POD, Freezing)),
                Released,
            ),
            (
                "new owner must not warm early in Draining",
                Some(assignment(OTHER)),
                Some(handoff(Some(OTHER), POD, Draining)),
                Released,
            ),
            (
                "new owner acquires in Warming",
                Some(assignment(OTHER)),
                Some(handoff(Some(OTHER), POD, Warming)),
                Acquiring,
            ),
            (
                "new owner serves at Complete",
                Some(assignment(POD)),
                Some(handoff(Some(OTHER), POD, Complete)),
                Serving,
            ),
            (
                "initial assignment (no old owner) acquires in Warming",
                None,
                Some(handoff(None, POD, Warming)),
                Acquiring,
            ),
            (
                "handoff between two other pods defers to owned assignment",
                Some(assignment(POD)),
                Some(handoff(Some(OTHER), THIRD, Draining)),
                Serving,
            ),
            (
                "handoff between two other pods defers to unowned assignment",
                Some(assignment(OTHER)),
                Some(handoff(Some(OTHER), THIRD, Warming)),
                Released,
            ),
            (
                "no handoff: owned assignment serves",
                Some(assignment(POD)),
                None,
                Serving,
            ),
            (
                "no handoff: someone else's assignment releases",
                Some(assignment(OTHER)),
                None,
                Released,
            ),
            ("no assignment at all releases", None, None, Released),
        ];

        for (case, assignment, handoff, expected) in cases {
            assert_eq!(
                desired_state(POD, assignment.as_ref(), handoff.as_ref()),
                expected,
                "{case}"
            );
        }
    }
}
