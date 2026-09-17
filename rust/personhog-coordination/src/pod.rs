use std::collections::{HashMap, HashSet};
use std::result::Result as StdResult;
use std::str::from_utf8;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use etcd_client::{EventType, WatchStream};
use futures::future::BoxFuture;
use futures::stream::{FuturesUnordered, StreamExt};
use metrics::{counter, gauge, histogram};
use tokio::sync::{Notify, Semaphore, SemaphorePermit};
use tokio::task::JoinError;
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use k8s_awareness::types::{ControllerKind, ControllerRef};
use k8s_awareness::{DepartureReason, K8sAwareness};

use crate::authority::AuthorityClock;
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
    ///
    /// May be cancelled mid-flight (the coordination loop is dropped on
    /// lease loss and shutdown) and re-invoked later for the same
    /// partition. Implementations must therefore leave no observable
    /// partial state on cancellation — buffer and install atomically, as
    /// the leader's warm does — because a cancelled warm is never
    /// released: the pod only tracks a warm once this returns.
    async fn warm_partition(&self, partition: u32) -> Result<()>;

    /// Owner: confirm this pod still holds whatever a partition needs in
    /// order to serve it, and re-take anything missing.
    ///
    /// Called on every convergence to `Serving`, including reconcile
    /// ticks, so it is the repair path for state the handoff protocol has
    /// no way back from — the leader uses it to re-take a changelog fence
    /// evicted by a broker rejection or lost to a failed abort. Running
    /// under `Serving` is what makes it safe: the pod re-takes only what
    /// the durable assignment says it owns, rather than what its local
    /// caches happen to still hold.
    ///
    /// Idempotent and cheap when nothing is missing, since it runs
    /// per-partition on every tick.
    /// Returns whether repair work was applied, so the convergence can
    /// count it as progress.
    async fn verify_serving(&self, _partition: u32) -> Result<bool> {
        Ok(false)
    }

    /// The handoff names this pod as the incoming owner, but acquisition
    /// is not yet permitted (the old owner is still freezing or
    /// draining). A hint, not a phase: implementations may use the
    /// window to prepare state whose setup touches nothing shared — the
    /// leader pre-connects its changelog producer here so the fence
    /// acquisition inside the warm pays only the init round trip. Called
    /// on every convergence observing that window, so implementations
    /// must be idempotent and must not block: spawn and return.
    async fn prepare_acquire(&self, _partition: u32) {}

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
    /// How many consecutive coordination-attempt failures the run
    /// supervisor tolerates before giving up and letting the process
    /// restart. An attempt that made real progress resets the count.
    pub run_retry_budget: u32,
    /// Base backoff between coordination attempts; doubles per
    /// consecutive failure up to a fixed cap.
    pub run_retry_backoff: Duration,
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

/// How long either exit path waits for its lease revoke before moving
/// on: unbounded, it waits out the very etcd outage that usually runs
/// it, while the registration expires by TTL anyway. Public because the
/// leader binary validates its shutdown budget against it at startup.
pub const REVOKE_TIMEOUT: Duration = Duration::from_secs(5);

/// The fence's drain bound on the shutdown path: its value there is
/// stopping admissions and a short straggler grace — anything the
/// graceful drain ahead of it could not quiesce will not quiesce now.
/// Public because the leader binary sums it into its budget check.
pub const SHUTDOWN_FENCE_BOUND: Duration = Duration::from_secs(3);

/// How long the drain's bookkeeping (Draining write, involvement
/// snapshot, watch creation) may take before degrading to the
/// fence-and-revoke teardown. These run before the drain's own timeout
/// starts, and an etcd whose KV path stalls while its lease path stays
/// healthy would otherwise hold shutdown here indefinitely. Public
/// because the leader binary sums it into its budget check.
pub const DRAIN_SETUP_BOUND: Duration = Duration::from_secs(5);

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
            run_retry_budget: 10,
            run_retry_backoff: Duration::from_millis(500),
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
    /// Partitions warmed by this process — local, dies with the process
    /// — each with the provenance of its warm.
    ///
    /// A std mutex on purpose, for both maps: an async lock leaves a
    /// suspension point between the warm installing in the data plane
    /// and the insert recording it, and a lane dropped there leaves a
    /// warm the self-fence cannot see. Guards held across an await are
    /// a compile error (`run` is spawned, the guard is not `Send`) and
    /// a clippy lint besides.
    warmed_partitions: StdMutex<HashMap<u32, WarmProvenance>>,
    /// Partitions this process has write-fenced via a drain — local,
    /// consulted so convergence to Serving only issues a resume when a
    /// fence actually exists. See `warmed_partitions` for why the lock
    /// is synchronous.
    fenced_partitions: StdMutex<HashSet<u32>>,
    /// Signalled when a partition is released, waking `drain()` without polling.
    drain_notify: Notify,
    /// Bounds concurrent `warm_partition` calls to `warm_concurrency`.
    warm_slots: Semaphore,
    /// Set when a lease-loss self-fence failed: local serving state may
    /// not reflect lost ownership, so the run supervisor must not retry
    /// in place — only a process restart clears this.
    fence_poisoned: AtomicBool,
    /// This pod's claim to serve, shared with the data plane and reset
    /// at each lease grant. Reads as invalid until the first grant.
    authority: Arc<AuthorityClock>,
    /// Optional K8s awareness for departure classification during shutdown.
    k8s_awareness: Option<Arc<K8sAwareness>>,
    /// Nudged when serving state broke in a way only a convergence can
    /// mend (the leader nudges when a changelog producer is condemned).
    /// The watch loop answers with an early reconcile pass, so repair
    /// happens now rather than on the next tick.
    repair_nudge: Option<Arc<Notify>>,
}

impl PodHandle {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        store: Arc<PersonhogStore>,
        config: PodConfig,
        handler: Arc<dyn HandoffHandler>,
        k8s_awareness: Option<Arc<K8sAwareness>>,
        // Shared with the data plane, which holds it from process start
        // and consults it per request.
        authority: Arc<AuthorityClock>,
    ) -> Self {
        let renewal_margin = AuthorityClock::renewal_margin(config.lease_ttl);
        assert!(
            config.heartbeat_interval < renewal_margin,
            "heartbeat_interval ({:?}) must be well under the keepalive renewal margin \
             (2/3 of lease_ttl = {renewal_margin:?}): the post-renewal sleep alone would \
             exhaust the margin and the pod would fence-loop against healthy etcd",
            config.heartbeat_interval,
        );
        let warm_slots = Semaphore::new(config.warm_concurrency);
        Self {
            store,
            config,
            handler,
            warmed_partitions: StdMutex::new(HashMap::new()),
            fenced_partitions: StdMutex::new(HashSet::new()),
            drain_notify: Notify::new(),
            warm_slots,
            fence_poisoned: AtomicBool::new(false),
            authority,
            k8s_awareness,
            repair_nudge: None,
        }
    }

    /// Run a reconcile pass whenever `nudge` fires, in addition to the
    /// periodic tick. The nudging end announces breakage the protocol
    /// has no event for — the leader's condemned changelog producer —
    /// and this is what turns its repair latency from one reconcile
    /// interval into one convergence.
    pub fn with_repair_nudge(mut self, nudge: Arc<Notify>) -> Self {
        self.repair_nudge = Some(nudge);
        self
    }

    /// This pod's claim to serve, for the data plane to consult on the
    /// request path. Invalid until the first lease is granted.
    pub fn authority(&self) -> Arc<AuthorityClock> {
        Arc::clone(&self.authority)
    }

    /// Run the pod's coordination, supervised at two levels so a
    /// failure costs exactly the authority it invalidates and nothing
    /// more. The **session** level owns the lease: grant, register,
    /// heartbeat. The **attempt** level (`run_once`) owns only
    /// convergence and the handoff watch.
    ///
    /// An attempt failure — a broken watch stream, a failed etcd write,
    /// a phase-handler error — retries in place with the lease and
    /// registration intact: the coordinator keeps seeing a live pod, so
    /// it never runs the dead-owner path against a process that is
    /// still serving, and the data plane keeps its cache. That is the
    /// invariant this split enforces: serving authority is held exactly
    /// as long as the lease-backed registration the coordinator's view
    /// derives from. A handoff that tries to move a partition away
    /// while the watch is down stalls awaiting this pod's ack and
    /// resolves through the phase-deadline replacement machinery.
    ///
    /// Only lease loss ends a session, and it still self-fences — now
    /// locally: every held partition is released before a new session
    /// registers afresh, because the coordinator treats the expired
    /// lease as death and may already be reassigning. Re-acquisition
    /// always re-warms. A failed local fence poisons recovery and the
    /// error propagates so a process restart clears everything.
    ///
    /// The registration asymmetry with the router is deliberate: a pod
    /// holds data authority, so its registration must survive attempt
    /// failures; a router holds freeze-quorum membership, so it sheds
    /// its registration fast — a registered but non-acking router would
    /// stall every freeze quorum until the phase deadline.
    pub async fn run(&self, cancel: CancellationToken) -> Result<()> {
        util::preregister_pod_metrics();
        let mut consecutive_failures: u32 = 0;
        // Set by the coordination loop whenever it applies real work
        // (a convergence completed); consumed by each failure note to
        // decide crash-loop vs fresh failure.
        let progress = AtomicBool::new(false);
        loop {
            // Cancel-aware internally — see `begin_session` for why the
            // race lives inside the call rather than around it.
            let (lease_id, granted_at) = match self.begin_session(&cancel).await {
                Ok(None) => return Ok(()),
                Ok(Some(session)) => session,
                Err(e) => {
                    if cancel.is_cancelled() {
                        return Ok(());
                    }
                    if !self.note_run_failure(&mut consecutive_failures, &progress, &e) {
                        return Err(e);
                    }
                    if self.run_backoff(&cancel, consecutive_failures).await {
                        return Ok(());
                    }
                    continue;
                }
            };

            // The heartbeat is session-scoped and outlives attempts: were
            // it attempt-scoped, a failed attempt would let the lease
            // lapse and reopen the deregistered-but-serving hole the
            // session split exists to close. It keeps running through the
            // drain phase too, so the coordinator sees a Draining pod
            // rather than a crashed one.
            // A new lease is a new claim: reset the shared clock rather
            // than replacing it, so the data plane's handle carries the
            // new session without re-plumbing.
            self.authority.begin_session(
                AuthorityClock::renewal_margin(self.config.lease_ttl),
                granted_at,
            );

            // The keepalive learns of a revoked lease on its next round,
            // which is up to a heartbeat away — and in that window the
            // coordinator has already seen the deletion and can reassign,
            // warm a successor, and let it start accepting writes while
            // this pod still answers reads from a cache that is no longer
            // the truth. Watching our own registration collapses that
            // window to a watch delivery.
            //
            // Deliberately best-effort: it accelerates detection, it does
            // not own it. If the stream never establishes or dies, the
            // keepalive's margin remains the guarantee, exactly as before.
            let heartbeat_cancel = CancellationToken::new();
            let registration_cancel = CancellationToken::new();
            let registration_watch = {
                let store = Arc::clone(&self.store);
                let authority = Arc::clone(&self.authority);
                let pod_name = self.config.pod_name.clone();
                let token = registration_cancel.child_token();
                // Ending the session is the keepalive's job, so the watch
                // ends it the same way rather than inventing a second
                // path: stopping the heartbeat makes the attempt loop
                // take the lease-loss branch it already has, which
                // fences, releases, and registers anew.
                let end_session = heartbeat_cancel.clone();
                tokio::spawn(async move {
                    watch_own_registration(store, pod_name, authority, end_session, token).await;
                })
            };

            let mut heartbeat_handle = {
                let store = Arc::clone(&self.store);
                let interval = self.config.heartbeat_interval;
                let lease_ttl = self.config.lease_ttl;
                let token = heartbeat_cancel.child_token();
                let authority = Arc::clone(&self.authority);
                tokio::spawn(async move {
                    util::run_lease_keepalive(
                        store,
                        lease_id,
                        interval,
                        lease_ttl,
                        granted_at,
                        "pod",
                        Some(authority),
                        token,
                    )
                    .await
                })
            };

            let mut lease_err: Option<Error> = None;
            let mut fatal: Option<Error> = None;
            // Attempts under this lease. The outer `select!` is what
            // guarantees prompt exit even when the watch loop is parked
            // inside a phase handler: the loop's own cancel check only
            // runs between iterations, so racing the token here drops the
            // in-flight future via cancel-by-drop, unwinding a stuck
            // handler. The heartbeat is raced for the same reason — a pod
            // that outlives its lease is a zombie, and lease loss must
            // end the session immediately.
            loop {
                let result = tokio::select! {
                    r = self.run_once(cancel.clone(), &progress) => r,
                    r = &mut heartbeat_handle => {
                        let err = Self::heartbeat_exit_error(r);
                        tracing::error!(
                            pod = %self.config.pod_name,
                            error = %err,
                            "lease keepalive failed; self-fencing"
                        );
                        lease_err = Some(err);
                        break;
                    }
                    _ = cancel.cancelled() => Ok(()),
                };
                if cancel.is_cancelled() {
                    break;
                }
                let err = match result {
                    Ok(()) => break,
                    Err(e) => e,
                };
                if !self.note_run_failure(&mut consecutive_failures, &progress, &err) {
                    fatal = Some(err);
                    break;
                }
                // The nap races the heartbeat: every await under a live
                // lease must observe lease loss promptly, and this one
                // otherwise defers it by a full backoff period — the
                // coordinator may already be reassigning while the pod
                // serves, unaware, until the nap ends.
                tokio::select! {
                    stop = self.run_backoff(&cancel, consecutive_failures) => {
                        if stop {
                            break;
                        }
                    }
                    r = &mut heartbeat_handle => {
                        let err = Self::heartbeat_exit_error(r);
                        tracing::error!(
                            pod = %self.config.pod_name,
                            error = %err,
                            "lease keepalive failed during backoff; self-fencing"
                        );
                        lease_err = Some(err);
                        break;
                    }
                }
                // Next attempt runs under the same lease: the
                // registration was never given up, so the coordinator's
                // view of this pod is unbroken.
            }

            // Graceful drain only on external shutdown with a live
            // lease. Skipped on lease loss: the coordinator already
            // considers this pod dead and is reassigning via the
            // dead-owner path — a graceful drain would only race it, and
            // every status write would fail against the expired lease.
            // The drain itself races the heartbeat for the same reason
            // as every other live-lease await: the pod serves its
            // partitions until their handoffs complete, so a lease lost
            // mid-drain must switch to the local self-fence immediately
            // rather than draining leaseless until the timeout.
            if cancel.is_cancelled() && lease_err.is_none() {
                tokio::select! {
                    r = self.drain(lease_id, &progress) => {
                        if let Err(e) = r {
                            tracing::warn!(pod = %self.config.pod_name, error = %e, "drain failed");
                        }
                    }
                    r = &mut heartbeat_handle => {
                        let err = Self::heartbeat_exit_error(r);
                        tracing::error!(
                            pod = %self.config.pod_name,
                            error = %err,
                            "lease keepalive failed during drain; self-fencing"
                        );
                        lease_err = Some(err);
                    }
                }
            }
            let lease_lost = lease_err.is_some();

            if !lease_lost {
                // Fence before the registration disappears: revoking the
                // lease deletes it instantly, and the dead-owner path the
                // coordinator then runs has no fence of its own — its
                // safety rests on a deregistered owner being unable to
                // produce. This matters most on the budget-exhausted
                // path, where the pod still holds and serves every
                // partition; after a completed graceful drain it is a
                // no-op. The heartbeat is still running here, so the
                // fence has no lease-runway pressure — but on the
                // shutdown path it does have a lifecycle budget: the
                // graceful drain may already have spent its full
                // timeout, and the process supervisor's window and the
                // pod's termination grace period are sized around one
                // drain timeout plus headroom, not two. Anything the
                // drain could not quiesce in thirty seconds will not
                // quiesce now; the fence's value here is stopping
                // admissions (milliseconds) and giving stragglers a
                // short grace, so its drain bound is a few seconds. The
                // budget-exhausted path is not on the shutdown clock and
                // keeps the full timeout.
                let fence_bound = if cancel.is_cancelled() {
                    SHUTDOWN_FENCE_BOUND.min(self.config.drain_timeout)
                } else {
                    self.config.drain_timeout
                };
                if let Err(e) = self.self_fence_locally(fence_bound).await {
                    self.fence_poisoned.store(true, Ordering::SeqCst);
                    tracing::error!(
                        pod = %self.config.pod_name,
                        error = %e,
                        "pre-revoke self-fence failed; refusing in-place recovery"
                    );
                }
                // Only now do we stop being the owner. On this path the
                // lease is still alive and the registration still stands:
                // surrendering before the drain would refuse reads the
                // protocol deliberately keeps serving — the old owner's
                // cache is the latest state right up to cutover — while
                // the coordinator, seeing a live owner, reassigns
                // nothing.
                self.authority.surrender();
                registration_cancel.cancel();
                drop(registration_watch.await);
                heartbeat_cancel.cancel();
                drop(heartbeat_handle.await);
                // Bounded like the lease-loss path's revoke: this path
                // is on the shutdown clock, and an unbounded revoke
                // against a hung etcd would spend the termination grace
                // the drain and fence are budgeted out of.
                drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
            } else {
                // Self-fence locally before any new session: every held
                // partition is released, dropping its cache and serving
                // authority. Re-acquisition always re-warms, so nothing
                // is lost but memory. A failed release poisons recovery.
                // The drain budget is the lease runway the keepalive
                // margin reserved — a third of the TTL — not the full
                // graceful drain timeout: the coordinator reassigns at
                // expiry, and a fence still draining past it loses the
                // race it exists to win. Overshoot poisons, and the
                // process restart clears stragglers by death.
                // Authority is already gone, so stop serving as the owner
                // before the drain rather than after it: the coordinator
                // may be reassigning right now, and a drain can take
                // seconds. A stale stamp merely expires; lease loss is a
                // fact that must not be undone by a renewal racing in
                // behind us, which is why this latches.
                self.authority.surrender();
                registration_cancel.cancel();
                drop(registration_watch.await);
                let runway = Duration::from_secs(self.config.lease_ttl.max(0) as u64) / 3;
                if let Err(e) = self
                    .self_fence_locally(runway.min(self.config.drain_timeout))
                    .await
                {
                    self.fence_poisoned.store(true, Ordering::SeqCst);
                    tracing::error!(
                        pod = %self.config.pod_name,
                        error = %e,
                        "local self-fence failed; refusing in-place recovery"
                    );
                }
                // Usually the lease is already dead here and this is a
                // dropped error. The registration watch also lands on
                // this branch when the key was deleted out from under a
                // live lease (an operator `del`, not a revoke) — without
                // this, that lease would sit alive and unreferenced for
                // its full TTL while the next session grants a second
                // one. Strictly after the self-fence and bounded: this
                // is cleanup, an unhealthy etcd is the usual reason for
                // being on this branch, and the store has no request
                // timeouts of its own — unbounded it could hold up the
                // fence or the next session for as long as the outage.
                drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
            }

            if let Some(e) = fatal {
                return Err(e);
            }
            if cancel.is_cancelled() {
                return Ok(());
            }
            match lease_err {
                Some(e) => {
                    if self.fence_poisoned.load(Ordering::SeqCst) {
                        // Serving state may not reflect the lost
                        // ownership; only a process restart clears it.
                        return Err(e);
                    }
                    if !self.note_run_failure(&mut consecutive_failures, &progress, &e) {
                        return Err(e);
                    }
                    if self.run_backoff(&cancel, consecutive_failures).await {
                        return Ok(());
                    }
                    // New session: fresh lease, fresh registration,
                    // ownership re-acquired through the warm path.
                }
                None => return Ok(()),
            }
        }
    }

    /// Classify the session keepalive task's exit. Any exit while the
    /// session is live means the lease can no longer be trusted.
    fn heartbeat_exit_error(result: StdResult<Result<()>, JoinError>) -> Error {
        match result {
            Ok(Ok(())) => Error::invalid_state("lease keepalive exited unexpectedly".to_string()),
            Ok(Err(e)) => e,
            Err(join_err) => Error::invalid_state(format!("keepalive task panicked: {join_err}")),
        }
    }

    /// Grant a fresh lease and register under it — the start of a
    /// coordination session. Returns `None` when cancellation arrived
    /// first.
    ///
    /// The race lives inside because the two steps abandon differently:
    /// an abandoned grant leaves only a lease that expires on its TTL,
    /// but an abandoned registration can still land — a phantom pod the
    /// coordinator plans toward — so past the grant, any abandonment
    /// revokes the lease, which deletes a landed registration or makes
    /// etcd reject a late one. Only a revoke that itself times out
    /// leaves the phantom, TTL-bounded; see the README's residual.
    async fn begin_session(&self, cancel: &CancellationToken) -> Result<Option<(i64, Instant)>> {
        // The server's TTL countdown starts at the grant; anchoring the
        // keepalive's margin clock any later would overstate runway by
        // however long registration took.
        let granted_at = Instant::now();
        let lease_id = tokio::select! {
            _ = cancel.cancelled() => return Ok(None),
            granted = self.store.grant_lease(self.config.lease_ttl) => granted?,
        };
        let registered = tokio::select! {
            _ = cancel.cancelled() => {
                drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
                return Ok(None);
            }
            registered = self.register(lease_id) => registered,
        };
        if let Err(e) = registered {
            // A failed registration may also have half-landed; the same
            // revoke clears it rather than leaving the lease to its TTL.
            drop(tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id)).await);
            return Err(e);
        }
        tracing::info!(pod = %self.config.pod_name, "registered with etcd");
        Ok(Some((lease_id, granted_at)))
    }

    /// See `util::note_run_failure` for the progress-based reset
    /// semantics.
    fn note_run_failure(&self, consecutive: &mut u32, progress: &AtomicBool, err: &Error) -> bool {
        util::note_run_failure(
            consecutive,
            progress,
            self.config.run_retry_budget,
            "pod",
            &self.config.pod_name,
            err,
        )
    }

    /// Exponential backoff between recovery steps. Returns `true` when
    /// cancelled during the wait.
    async fn run_backoff(&self, cancel: &CancellationToken, consecutive: u32) -> bool {
        const BACKOFF_CAP: Duration = Duration::from_secs(15);
        let backoff = self
            .config
            .run_retry_backoff
            .saturating_mul(2u32.saturating_pow(consecutive.saturating_sub(1)))
            .min(BACKOFF_CAP);
        tokio::select! {
            _ = cancel.cancelled() => true,
            _ = tokio::time::sleep(backoff) => false,
        }
    }

    /// One coordination attempt under a live session: converge every
    /// involved partition from a fresh snapshot, then watch. Holds no
    /// lease state — the session and its heartbeat outlive any number of
    /// failed attempts. Convergence-before-watching is what makes each
    /// attempt (and a crash-restart within the lease TTL) safe: local
    /// state is re-derived from durable state, cold assigned partitions
    /// re-warm, in-flight handoffs get their drain/warm/ack, completed
    /// ones release, and the watch anchors to the snapshot revision so
    /// nothing between snapshot and attach is lost.
    async fn run_once(&self, cancel: CancellationToken, progress: &AtomicBool) -> Result<()> {
        let (initial, snapshot_revision) = self.involved_partitions().await?;
        let stream = self
            .store
            .watch_handoffs_from(snapshot_revision + 1)
            .await?;
        self.watch_handoff_loop(stream, cancel, initial, progress)
            .await
    }

    /// Fence, quiesce, and release every locally held partition —
    /// warmed or fenced — through the handler, clearing the pod's local
    /// ownership state. Purely local: no etcd writes, callable with no
    /// lease.
    ///
    /// The order per partition is load-bearing for what release
    /// exposes, not for the writes already in flight: an admitted write
    /// completes its produce and acks whatever this function does —
    /// neither the fence nor a withheld release can stop it. Draining
    /// first (fence, then wait for the inflight counter) means the
    /// release that follows unfences a partition with nothing left in
    /// flight — no fresh admission lands on a leaseless pod, and the
    /// cache is not dropped out from under a handler still using it —
    /// and once this returns cleanly, everything this pod admitted had
    /// acked before any partition was let go. Each drain is bounded by
    /// the drain timeout; a partition that cannot quiesce stays fenced,
    /// held, and unreleased — its in-flight work's fate belongs to the
    /// broker (fenced, or committed below the successor's cutoff; with
    /// fencing off it is the documented unfenced residual) — and the
    /// caller poisons the run so the process restart clears it by
    /// death, exactly as the pre-supervisor design did. The window before the lease loss is
    /// even *detected* (up to one heartbeat tick) remains the
    /// documented zombie residual; this closes only the part the local
    /// fence itself controls.
    async fn self_fence_locally(&self, drain_bound: Duration) -> Result<()> {
        let held: HashSet<u32> = {
            let warmed = self
                .warmed_partitions
                .lock()
                .expect("warmed partitions lock poisoned");
            let fenced = self
                .fenced_partitions
                .lock()
                .expect("fenced partitions lock poisoned");
            warmed
                .keys()
                .copied()
                .chain(fenced.iter().copied())
                .collect()
        };
        // Phase 1: fence and quiesce every partition CONCURRENTLY. Each
        // drain fences as its first action, so running them together
        // stops all admissions within milliseconds of each other and
        // bounds the whole quiesce by a single drain timeout. Draining
        // sequentially would leave later partitions serving — leaseless
        // — while earlier ones wait out their in-flight work, extending
        // the zombie window per held partition.
        let mut drains = tokio::task::JoinSet::new();
        for &partition in &held {
            let handler = Arc::clone(&self.handler);
            let timeout = drain_bound;
            drains.spawn(async move {
                tokio::time::timeout(timeout, handler.drain_partition_inflight(partition))
                    .await
                    .map_err(|_| {
                        Error::invalid_state(format!(
                            "self-fence drain timed out for partition {partition}"
                        ))
                    })??;
                Ok::<u32, Error>(partition)
            });
        }
        // Failures are collected rather than propagated. This runs
        // because the pod has lost the right to serve, so giving the
        // partitions up matters more than reporting why one of them
        // resisted — returning on the first error would leave every
        // other partition still served by a pod with no lease, which is
        // the zombie this function exists to prevent.
        let mut failures: Vec<String> = Vec::new();
        let mut quiesced: HashSet<u32> = HashSet::new();
        while let Some(joined) = drains.join_next().await {
            match joined {
                Ok(Ok(partition)) => {
                    quiesced.insert(partition);
                }
                Ok(Err(e)) => failures.push(e.to_string()),
                Err(e) => failures.push(format!("self-fence drain panicked: {e}")),
            }
        }

        // Phase 2: release each partition that quiesced — dropping its
        // cache and serving authority — and clear the local ownership
        // state for it.
        //
        // Only the ones that quiesced. A write still in flight acks
        // whether or not its partition is released — nothing can stop
        // it — so what releasing an un-quiesced partition would actually
        // do is unfence fresh admissions on a pod with no lease, drop
        // the cache out from under the handlers still using it, and
        // erase the record that the partition was never given up. One
        // left fenced and unreleased stays that way until the process
        // restarts, which is the outcome its drain timing out already
        // implies.
        for partition in held {
            if !quiesced.contains(&partition) {
                continue;
            }
            if let Err(e) = self.handler.release_partition(partition).await {
                failures.push(format!("release of partition {partition}: {e}"));
                // Still held: the handler may retain the cache and the
                // serving authority, so forgetting it here would make the
                // closing gauge read a partition as given up that was
                // not. The run is about to end poisoned either way.
                continue;
            }
            self.warmed_partitions
                .lock()
                .expect("warmed partitions lock poisoned")
                .remove(&partition);
            self.fenced_partitions
                .lock()
                .expect("fenced partitions lock poisoned")
                .remove(&partition);
        }
        // Whatever is left, not zero. A partition whose drain never
        // quiesced is still held, and reporting none held would hide it
        // at the one moment the count is worth reading.
        gauge!("personhog_coordination_partitions_held").set(self.held_partition_count() as f64);
        if !failures.is_empty() {
            return Err(Error::invalid_state(format!(
                "self-fence completed with {} failure(s): {}",
                failures.len(),
                failures.join("; ")
            )));
        }
        Ok(())
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
    async fn drain(&self, lease_id: i64, progress: &AtomicBool) -> Result<()> {
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

        // The bookkeeping is bounded as one unit: a timeout surfaces as
        // an error, and a failed drain already degrades to the
        // fence-and-revoke teardown, which is exactly what a shutdown
        // stuck on a stalled KV path should do.
        let setup = async {
            self.store
                .update_pod_status(&self.config.pod_name, PodStatus::Draining, lease_id)
                .await?;

            tracing::info!(
                pod = %self.config.pod_name,
                reason = %reason,
                "set status to Draining, waiting for partition handoffs"
            );

            if self.held_partition_count() == 0 {
                return Ok(None);
            }

            // Keep converging during drain so partitions release as the
            // coordinator completes their handoffs. Reconcile first — a
            // Complete written while the main loop was winding down would
            // otherwise be missed — and anchor the fresh watch to the
            // snapshot's revision.
            let (initial, snapshot_revision) = self.involved_partitions().await?;
            let stream = self
                .store
                .watch_handoffs_from(snapshot_revision + 1)
                .await?;
            Ok::<_, Error>(Some((initial, stream)))
        };
        let Some((initial, stream)) = tokio::time::timeout(DRAIN_SETUP_BOUND, setup)
            .await
            .map_err(|_| {
                Error::invalid_state(format!(
                    "drain setup exceeded {DRAIN_SETUP_BOUND:?}; degrading to fence and revoke"
                ))
            })??
        else {
            tracing::info!(pod = %self.config.pod_name, "no partitions to drain");
            return Ok(());
        };
        let drain_cancel = CancellationToken::new();

        tokio::select! {
            r = self.watch_handoff_loop(stream, drain_cancel.clone(), initial, progress) => {
                r?;
            },
            _ = self.wait_for_drain() => {
                tracing::info!(pod = %self.config.pod_name, "all partitions drained successfully");
            },
            _ = tokio::time::sleep(self.config.drain_timeout) => {
                let remaining = self.held_partition_count();
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
    fn held_partition_count(&self) -> usize {
        let warmed = self
            .warmed_partitions
            .lock()
            .expect("warmed partitions lock poisoned");
        let fenced = self
            .fenced_partitions
            .lock()
            .expect("fenced partitions lock poisoned");
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
            if self.held_partition_count() == 0 {
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
        partitions.extend(
            self.warmed_partitions
                .lock()
                .expect("warmed partitions lock poisoned")
                .keys()
                .copied(),
        );
        partitions.extend(
            self.fenced_partitions
                .lock()
                .expect("fenced partitions lock poisoned")
                .iter()
                .copied(),
        );

        tracing::info!(
            pod,
            partitions = partitions.len(),
            "reconciling local state against durable state"
        );

        Ok((partitions, rev_a.min(rev_h)))
    }

    /// Whether this pod still holds something for the partition: a warm
    /// cache or a write fence. Local state outlives the durable record
    /// that created it, which is what makes a pod care about a handoff
    /// that no longer names it — a cancellation leaves the old owner
    /// fenced, and only the fence says so.
    fn holds_local_state(&self, partition: u32) -> bool {
        if self
            .warmed_partitions
            .lock()
            .expect("warmed partitions lock poisoned")
            .contains_key(&partition)
        {
            return true;
        }
        self.fenced_partitions
            .lock()
            .expect("fenced partitions lock poisoned")
            .contains(&partition)
    }
}

/// Whether a handoff event concerns the pod that observed it — the
/// scoping that keeps a fleet-wide rebalance from costing every pod a
/// convergence (two point reads) on every partition's event.
///
/// `handoff` is `None` for a deletion, which carries no owners; only
/// the pod's own involvement can decide, and must — a cancelled handoff
/// has to reach the old owner holding its fence and the new owner still
/// warming. `converging` covers the warm window, where the pod holds
/// neither cache nor fence yet: dispatching coalesces onto the running
/// convergence, which re-derives once the warm completes.
///
/// Split out so both directions can be pinned: widening this to always
/// return true costs nothing any convergence test observes.
fn event_concerns_pod(
    pod_name: &str,
    handoff: Option<&HandoffState>,
    holds_local_state: bool,
    converging: bool,
) -> bool {
    let named = handoff.is_some_and(|h| {
        h.old_owner.as_deref() == Some(pod_name) || h.new_owner.as_str() == pod_name
    });
    named || holds_local_state || converging
}

impl PodHandle {
    /// Re-derive and apply the desired state for one partition from fresh
    /// point reads. Every watch event is just a signal to look again —
    /// convergence acts on observed durable state, never on remembered
    /// event payloads, so missed, reordered, or replayed events cannot
    /// corrupt local state.
    async fn converge(&self, partition: u32) -> Result<bool> {
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
    ///
    /// Returns whether the application changed local state (a warm, a
    /// fence, a resume, a release). A convergence that merely confirms
    /// the partition is already settled is a read, and the run budget's
    /// progress signal must not count it — a pod whose coordination is
    /// wedged still no-op-converges its settled partitions successfully.
    async fn apply(
        &self,
        partition: u32,
        assignment: Option<&PartitionAssignment>,
        handoff: Option<&HandoffState>,
    ) -> Result<bool> {
        let pod = &self.config.pod_name;
        let desired = desired_state(pod, assignment, handoff);
        let mut did_work = false;

        // The pending-ownership window: this pod will be told to warm
        // once the drain completes, and everything the warm needs that
        // touches no shared state can get ready now. Deliberately not a
        // DesiredState — the derivation stays a pure ownership answer —
        // and deliberately not `did_work`: preparation is a hint, and
        // counting it as progress would let a pod that only ever
        // prepares look healthy to the budgets.
        if let Some(h) = handoff {
            if h.new_owner == *pod
                && matches!(h.phase, HandoffPhase::Freezing | HandoffPhase::Draining)
            {
                self.handler.prepare_acquire(partition).await;
            }
        }

        match desired {
            DesiredState::Serving => {
                if !self
                    .warmed_partitions
                    .lock()
                    .expect("warmed partitions lock poisoned")
                    .contains_key(&partition)
                {
                    tracing::info!(pod, partition, "converging to Serving: warming");
                    let _warm_slot = self.acquire_warm_slot().await?;
                    let start = Instant::now();
                    self.handler.warm_partition(partition).await?;
                    histogram!("personhog_coordination_partition_warm_ms", "trigger" => "restart")
                        .record(start.elapsed().as_secs_f64() * 1000.0);
                    self.warmed_partitions
                        .lock()
                        .expect("warmed partitions lock poisoned")
                        .insert(partition, WarmProvenance::Serving);
                    did_work = true;
                }
                // Whatever the branch above did, the pod is meant to be
                // serving this partition now — so let the handler repair
                // anything it needs and no longer has. Repair applied is
                // progress like any other applied work.
                if self.handler.verify_serving(partition).await? {
                    did_work = true;
                }
                // Resume any local fence regardless of which branch ran:
                // a crash-restart inside the TTL can leave a partition
                // fenced but unwarmed (re-fenced through the Drained arm
                // before the handoff was cancelled), and relying on the
                // handler's warm to lift the fence would make write
                // admission depend on an undocumented handler side
                // effect. Resuming after a warm that already unfenced is
                // an idempotent no-op.
                //
                // Clear the local record only once the handler has
                // actually resumed: `resume_partition` can fail (it may
                // re-take broker-side state), and forgetting the fence
                // first would leave the data plane fenced with no branch
                // left to re-enter — writes rejected forever while the
                // convergence reports success.
                if self
                    .fenced_partitions
                    .lock()
                    .expect("fenced partitions lock poisoned")
                    .contains(&partition)
                {
                    tracing::info!(pod, partition, "converging to Serving: resuming writes");
                    self.handler.resume_partition(partition).await?;
                    self.fenced_partitions
                        .lock()
                        .expect("fenced partitions lock poisoned")
                        .remove(&partition);
                    did_work = true;
                }
            }
            DesiredState::Drained { ack } => {
                // The coordinator only advances Freezing → Draining once
                // every router has FreezeAcked, so no new request can flow
                // from any router to this pod and the inflight==0 the drain
                // waits for is meaningful. The produce path awaits Kafka
                // delivery before returning, so "no inflight handlers"
                // implies "every acked write is durable in Kafka."
                let newly_fencing = !self
                    .fenced_partitions
                    .lock()
                    .expect("fenced partitions lock poisoned")
                    .contains(&partition);
                if newly_fencing {
                    tracing::info!(pod, partition, "converging to Drained: fencing + draining");
                    did_work = true;
                }
                // Record the fence before the call that applies it. The
                // handler fences as its first action and only then waits,
                // so a failure after that point would otherwise leave the
                // data plane fenced with nothing here to say so — and a
                // later convergence to Serving, seeing no fence recorded,
                // would skip the resume that lifts it. Recording early
                // only risks a redundant resume, which is a no-op.
                self.fenced_partitions
                    .lock()
                    .expect("fenced partitions lock poisoned")
                    .insert(partition);
                let start = Instant::now();
                self.handler.drain_partition_inflight(partition).await?;
                if newly_fencing {
                    // Only the first convergence does a real drain wait;
                    // later re-convergences are no-ops that would bury the
                    // signal in near-zero samples.
                    histogram!("personhog_coordination_partition_drain_ms")
                        .record(start.elapsed().as_secs_f64() * 1000.0);
                }
                if ack {
                    let handoff = handoff.expect("Drained state only derives from a handoff");
                    self.store
                        .put_drained_ack(&PodDrainedAck {
                            pod_name: pod.clone(),
                            partition,
                            acked_at: util::now_seconds(),
                            acked_at_ms: 0,
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
                let valid = self.warmed_partitions.lock().expect("warmed partitions lock poisoned").get(&partition).is_some_and(
                    |provenance| {
                        matches!(provenance, WarmProvenance::Handoff(id) if *id == handoff.handoff_id)
                    },
                );
                if !valid {
                    if self
                        .warmed_partitions
                        .lock()
                        .expect("warmed partitions lock poisoned")
                        .contains_key(&partition)
                    {
                        tracing::info!(
                            pod,
                            partition,
                            "converging to Acquiring: releasing a warm from an earlier era"
                        );
                        self.handler.release_partition(partition).await?;
                        self.warmed_partitions
                            .lock()
                            .expect("warmed partitions lock poisoned")
                            .remove(&partition);
                    }
                    tracing::info!(pod, partition, "converging to Acquiring: warming");
                    let _warm_slot = self.acquire_warm_slot().await?;
                    let start = Instant::now();
                    self.handler.warm_partition(partition).await?;
                    histogram!("personhog_coordination_partition_warm_ms", "trigger" => "handoff")
                        .record(start.elapsed().as_secs_f64() * 1000.0);
                    self.warmed_partitions
                        .lock()
                        .expect("warmed partitions lock poisoned")
                        .insert(
                            partition,
                            WarmProvenance::Handoff(handoff.handoff_id.clone()),
                        );
                    did_work = true;
                }
                // The warm above re-admits writes for this partition as
                // part of taking ownership, so clearing the record here
                // matches the data plane rather than diverging from it.
                self.fenced_partitions
                    .lock()
                    .expect("fenced partitions lock poisoned")
                    .remove(&partition);
                self.store
                    .put_warmed_ack(&PodWarmedAck {
                        pod_name: pod.clone(),
                        partition,
                        acked_at: util::now_seconds(),
                        acked_at_ms: 0,
                        handoff_id: handoff.handoff_id.clone(),
                    })
                    .await?;
                tracing::info!(pod, partition, "warmed ack written");
            }
            DesiredState::Released => {
                // Forgotten only after the handler returns, matching the
                // discipline the other arms document. Removing first put
                // a suspension point between forgetting and releasing: a
                // lane dropped there — or a release that failed — left
                // the partition in neither map, so no convergence ever
                // dispatched for it again and its cache, floors, and
                // producer leaked for the life of the process. Release is
                // idempotent, so a retry that re-runs it costs nothing.
                let was_warmed = self
                    .warmed_partitions
                    .lock()
                    .expect("warmed partitions lock poisoned")
                    .contains_key(&partition);
                let was_fenced = self
                    .fenced_partitions
                    .lock()
                    .expect("fenced partitions lock poisoned")
                    .contains(&partition);
                if was_warmed || was_fenced {
                    tracing::info!(pod, partition, "converging to Released: releasing");
                    self.handler.release_partition(partition).await?;
                    self.warmed_partitions
                        .lock()
                        .expect("warmed partitions lock poisoned")
                        .remove(&partition);
                    self.fenced_partitions
                        .lock()
                        .expect("fenced partitions lock poisoned")
                        .remove(&partition);
                    counter!("personhog_coordination_partition_releases_total").increment(1);
                    self.drain_notify.notify_one();
                    did_work = true;
                }
            }
        }

        gauge!("personhog_coordination_partitions_held").set(self.held_partition_count() as f64);

        Ok(did_work)
    }

    async fn watch_handoff_loop(
        &self,
        mut stream: WatchStream,
        cancel: CancellationToken,
        initial: HashSet<u32>,
        progress: &AtomicBool,
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
        reconcile_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

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
        let mut lanes: FuturesUnordered<BoxFuture<'_, (u32, Trigger, Result<bool>)>> =
            FuturesUnordered::new();
        let mut in_flight: HashSet<u32> = HashSet::new();
        let mut pending: HashMap<u32, Trigger> = HashMap::new();

        // One nudge-driven pass per reconcile interval at most. A
        // producer that condemns again right after every heal would
        // otherwise drive passes at broker speed — and each successful
        // heal counts as applied work, resetting the budgets that exist
        // to catch exactly that wedge. A suppressed nudge falls back to
        // the tick, so a flap degrades to tick-rate healing, the
        // pre-nudge shape.
        let mut last_repair_pass: Option<tokio::time::Instant> = None;

        /// Resolves when the repair nudge fires, or never when none is
        /// wired, leaving the other arms in charge.
        async fn nudged(nudge: &Option<Arc<Notify>>) {
            match nudge {
                Some(nudge) => nudge.notified().await,
                None => std::future::pending().await,
            }
        }

        fn dispatch<'s>(
            handle: &'s PodHandle,
            partition: u32,
            trigger: Trigger,
            in_flight: &mut HashSet<u32>,
            pending: &mut HashMap<u32, Trigger>,
            lanes: &mut FuturesUnordered<BoxFuture<'s, (u32, Trigger, Result<bool>)>>,
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
                _ = nudged(&self.repair_nudge) => {
                    let now = tokio::time::Instant::now();
                    let cooling = last_repair_pass.is_some_and(|last| {
                        now.duration_since(last) < self.config.reconcile_interval
                    });
                    if cooling {
                        counter!("personhog_coordination_repair_passes_total", "outcome" => "suppressed")
                            .increment(1);
                        tracing::warn!(
                            pod = %self.config.pod_name,
                            "repair nudged again inside the cooldown; leaving it to the reconcile tick"
                        );
                    } else {
                        last_repair_pass = Some(now);
                        counter!("personhog_coordination_repair_passes_total", "outcome" => "run")
                            .increment(1);
                        tracing::info!(
                            pod = %self.config.pod_name,
                            "data-plane repair nudge; converging involved partitions"
                        );
                        // The same derivation the tick runs: the nudge
                        // carries no payload, and `verify_serving`
                        // repairs exactly the partitions that need it
                        // while the rest converge as no-ops. Reconcile
                        // severity throughout; a failed snapshot leaves
                        // repair to the tick, whose budget owns
                        // sustained failure.
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
                                tracing::warn!(
                                    pod = %self.config.pod_name,
                                    error = %e,
                                    "repair-pass snapshot failed; leaving repair to the reconcile tick"
                                );
                            }
                        }
                    }
                }
                msg = stream.message() => {
                    let resp = util::live_watch_response(msg?, "handoff")?;
                    for event in resp.events() {
                        let mut unreadable = false;
                        // Convergence still reads durable state rather
                        // than trusting the payload; the payload only
                        // decides whether to look. See
                        // `event_concerns_pod` for what makes an event
                        // this pod's business.
                        let partition = match event.event_type() {
                            EventType::Put => match parse_watch_value::<HandoffState>(event) {
                                Ok(handoff) => {
                                    util::record_phase_watch_delivery(
                                        "pod",
                                        handoff.phase,
                                        handoff.phase_entered_at_ms,
                                    );
                                    let partition = handoff.partition;
                                    if event_concerns_pod(
                                        &self.config.pod_name,
                                        Some(&handoff),
                                        self.holds_local_state(partition),
                                        in_flight.contains(&partition),
                                    ) {
                                        Some(partition)
                                    } else {
                                        None
                                    }
                                }
                                Err(e) => {
                                    tracing::error!(pod = %self.config.pod_name, error = %e, "failed to parse handoff");
                                    unreadable = true;
                                    None
                                }
                            },
                            EventType::Delete => match event
                                .kv()
                                .and_then(|kv| from_utf8(kv.key()).ok())
                                .and_then(store::extract_partition_from_key)
                            {
                                Some(p)
                                    if event_concerns_pod(
                                        &self.config.pod_name,
                                        None,
                                        self.holds_local_state(p),
                                        in_flight.contains(&p),
                                    ) =>
                                {
                                    Some(p)
                                }
                                Some(_) => None,
                                None => {
                                    unreadable = true;
                                    None
                                }
                            },
                        };
                        util::record_handoff_event_disposition(match (partition, unreadable) {
                            (Some(_), _) => "converged",
                            (None, true) => "unreadable",
                            (None, false) => "skipped",
                        });
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
                        Ok(did_work) => {
                            // Progress means *applied* work — a handler
                            // invoked, local serving state changed — never
                            // a successful read. A no-op convergence of an
                            // already-settled partition succeeds even on a
                            // pod whose coordination is otherwise wedged,
                            // and counting it would make the run budget
                            // unreachable in exactly that wedge.
                            if did_work {
                                progress.store(true, Ordering::SeqCst);
                            }
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

/// Surrender the moment this pod's own registration disappears.
///
/// A lease revoked or expired out from under a pod deletes its keys
/// immediately, but the pod only learns on its next keepalive round.
/// The coordinator sees the deletion at once and can reassign inside
/// that gap, so the pod can be answering reads from a cache the new
/// owner is already changing. This closes the gap to a watch delivery.
///
/// It is an accelerator, not the guarantee: a stream that never
/// establishes, or dies, simply leaves detection to the keepalive margin
/// as before, which is why nothing here retries or escalates.
async fn watch_own_registration(
    store: Arc<PersonhogStore>,
    pod_name: String,
    authority: Arc<AuthorityClock>,
    end_session: CancellationToken,
    cancel: CancellationToken,
) {
    // Establishment is raced against the token just like the stream
    // reads below: the session teardown joins this task, so an etcd call
    // stalling here would otherwise hold up the join — and behind it the
    // self-fence — for as long as the stall lasts.
    let revision = tokio::select! {
        _ = cancel.cancelled() => return,
        revision = store.current_revision() => match revision {
            Ok(revision) => revision,
            Err(e) => {
                tracing::warn!(pod = %pod_name, error = %e, "registration watch unavailable");
                return;
            }
        },
    };
    let mut stream = tokio::select! {
        _ = cancel.cancelled() => return,
        stream = store.watch_pods_from(revision + 1) => match stream {
            Ok(stream) => stream,
            Err(e) => {
                tracing::warn!(pod = %pod_name, error = %e, "registration watch unavailable");
                return;
            }
        },
    };
    let registration_key = store.pod_registration_key(&pod_name);
    loop {
        let message = tokio::select! {
            _ = cancel.cancelled() => return,
            message = stream.message() => message,
        };
        let Ok(Some(response)) = message else { return };
        // A cancelled watcher delivers nothing further. This watch is
        // defense-in-depth: the session teardown it accelerates still
        // happens without it, so ending is safe.
        if response.canceled() {
            tracing::warn!(pod = %pod_name, "registration watch cancelled by etcd; watch ends");
            return;
        }
        for event in response.events() {
            if event.event_type() != EventType::Delete {
                continue;
            }
            // Exactly the key `register` writes — this is a prefix
            // watch, and matching anything looser (say, a final path
            // segment) would let an unrelated deletion under the prefix
            // cost this pod its session.
            let deleted_us = event
                .kv()
                .and_then(|kv| from_utf8(kv.key()).ok())
                .is_some_and(|key| key == registration_key);
            if deleted_us {
                counter!("personhog_coordination_registration_deleted_total").increment(1);
                tracing::error!(
                    pod = %pod_name,
                    "registration deleted; surrendering serving authority immediately"
                );
                // Deliberately redundant with the session teardown's
                // surrender: this one stops strong reads at watch
                // delivery rather than when teardown finishes.
                authority.surrender();
                // Surrendering alone would leave a pod that holds a live
                // lease, refuses every read, and never registers again —
                // silently idle with nothing to escalate. Ending the
                // session is what puts it back to work.
                end_session.cancel();
                return;
            }
        }
    }
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

    /// An event a pod is party to must reach a convergence, by any of
    /// the three routes — and one it is not party to must not. The skip
    /// direction is the one worth having: every integration test passed
    /// before the scoping existed, so nothing else asserts it.
    #[test]
    fn an_event_reaches_only_the_pods_it_concerns() {
        let cases = [
            (
                "named as the old owner",
                Some(handoff(Some(POD), OTHER, HandoffPhase::Freezing)),
                false,
                false,
                true,
            ),
            (
                "named as the new owner",
                Some(handoff(Some(OTHER), POD, HandoffPhase::Warming)),
                false,
                false,
                true,
            ),
            (
                // A replacement overwrites the handoff key in place, so
                // an old owner dropped from the successor sees a put
                // naming two other pods. Only the fence it still holds
                // says the fence should come off.
                "unnamed but still holding a fence or a cache",
                Some(handoff(Some(OTHER), THIRD, HandoffPhase::Freezing)),
                true,
                false,
                true,
            ),
            (
                "unnamed but converging it right now",
                Some(handoff(Some(OTHER), THIRD, HandoffPhase::Freezing)),
                false,
                true,
                true,
            ),
            (
                "a deletion, while holding local state for it",
                None,
                true,
                false,
                true,
            ),
            (
                "a deletion, while still warming for it",
                None,
                false,
                true,
                true,
            ),
            (
                "another pods' handoff, holding nothing and converging nothing",
                Some(handoff(Some(OTHER), THIRD, HandoffPhase::Freezing)),
                false,
                false,
                false,
            ),
            (
                "a deletion for a partition this pod has nothing to do with",
                None,
                false,
                false,
                false,
            ),
        ];

        for (case, handoff, holds_local_state, converging, expected) in cases {
            assert_eq!(
                event_concerns_pod(POD, handoff.as_ref(), holds_local_state, converging),
                expected,
                "{case}"
            );
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
            freeze_quorum_ref: None,
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
                // A cancelled handoff is replaced by a reaffirm toward
                // the current owner, and the coordinator deliberately
                // leaves `old_owner` unset on it: naming this pod on
                // both sides would match the old-owner arm first and
                // release the partition instead of resuming it. That is
                // a silent partition drop, so the shape is pinned here
                // rather than left to a comment.
                "reaffirmed owner resumes rather than releasing",
                Some(assignment(POD)),
                Some(handoff(None, POD, Complete)),
                Serving,
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
