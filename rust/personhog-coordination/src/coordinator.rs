use std::collections::hash_map::DefaultHasher;
use std::collections::{HashMap, HashSet};
use std::hash::{Hash, Hasher};
use std::str::from_utf8;
use std::sync::Arc;
use std::time::{Duration, Instant};

use etcd_client::{EventType, WatchStream};
use metrics::{counter, gauge, histogram};
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use k8s_awareness::types::{ControllerKind, ControllerRef};
use k8s_awareness::{classify_departure, ClusterIntent, DepartureReason, K8sAwareness};

use crate::error::{Error, Result};
use crate::protocol::{
    drain_satisfied, freeze_quorum_met, missing_freeze_ackers, past_phase_deadline,
    plan_partial_rebalance, warm_satisfied,
};
use crate::store::{self, PersonhogStore};
use crate::strategy::{AssignmentStrategy, Member, PlacementPolicy};
use crate::types::{
    AssignmentPrecondition, HandoffPhase, HandoffReplacement, HandoffState, PodStatus,
    RegisteredPod, RegisteredRouter,
};

use crate::util;

#[derive(Debug, Clone)]
pub struct CoordinatorConfig {
    pub name: String,
    pub leader_lease_ttl: i64,
    pub keepalive_interval: Duration,
    /// How long a standby waits on its leader-key watch before
    /// re-reading the key — the bound on how long a stalled watch can
    /// hide an opening, and the retry pace when the election cannot be
    /// observed at all.
    pub standby_poll_interval: Duration,

    pub run_retry_backoff: Duration,
    /// How long without a bad ending before the pace starts over —
    /// without decay, a bad spell in the morning charges an isolated
    /// evening failure the cap instead of the base.
    pub backoff_decay_window: Duration,
    /// How long to wait after the first pod event before rebalancing, to batch
    /// rapid pod registrations into a single rebalance.
    pub rebalance_debounce_interval: Duration,
    /// How often to re-evaluate in-flight handoffs regardless of watch
    /// events. Phase advancement is event-driven — acks, handoff writes,
    /// and router departures are all watched — so the tick is pure
    /// defense-in-depth: it catches a dropped stream or an event lost in
    /// a coordinator failover window, keeping a handoff from stalling
    /// indefinitely on a missed delivery.
    pub reconcile_interval: Duration,
    /// How long a handoff may sit in Freezing or Draining before the
    /// coordinator cancels it — by atomic replacement with whatever
    /// resolves its stashes — and lets the plan try again.
    ///
    /// This is the backstop for causes we have not found: a participant
    /// that never acks leaves a handoff that no other path removes, and
    /// an in-flight handoff pins its partition so no re-plan can touch
    /// it. Cancelling is the only safe response; force-advancing past a
    /// missing freeze ack is exactly the split-brain the quorum exists
    /// to prevent.
    ///
    /// Measured against time in the current phase (`phase_entered_at_ms`,
    /// which every phase advance restamps): wedged is a property of a
    /// phase, not of a lifetime. Freezing and Draining wait only on
    /// acknowledgements, so their budget can be tight; Warming does real
    /// work that scales with the partition and gets its own budget below.
    ///
    /// Generous by design: healthy ack waits complete in seconds, so
    /// this sits orders of magnitude above them. Ages are wall-clock
    /// differences that may span machines (a failover successor judges
    /// records its predecessor stamped); NTP-bounded skew against a
    /// deadline of minutes is tolerated, and a mistimed cancellation is
    /// safe in either direction — early, the replacement is stamped and
    /// judged by one clock; late, a wedge lives that much longer.
    pub handoff_deadline: Duration,
    /// How long a handoff may sit in Warming. A warm replays the
    /// partition's changelog, whose length scales with the data — under
    /// a general deadline a partition whose replay outlives the budget
    /// could never complete: cancel, replan, warm from zero, forever.
    /// Zero disables the Warming budget entirely.
    pub warming_deadline: Duration,
}

impl Default for CoordinatorConfig {
    fn default() -> Self {
        Self {
            name: "coordinator-0".to_string(),
            // Succession follows the key's deletion, so the TTL bounds
            // a crashed leader's outage: 5s sits near the pod-crash
            // detection window, and the 1s keepalive gives several
            // renewal attempts inside it. Graceful exits revoke instead.
            leader_lease_ttl: 5,
            keepalive_interval: Duration::from_secs(1),
            // An idle standby's whole etcd cost: one read and one watch
            // stream per interval, bounding a silently stalled watch.
            standby_poll_interval: Duration::from_secs(5),
            // Doubles per consecutive bad ending, capped at the lease
            // TTL (see `pace_after_ending`'s invariant).
            run_retry_backoff: Duration::from_millis(500),
            backoff_decay_window: Duration::from_secs(300),
            rebalance_debounce_interval: Duration::from_secs(1),
            reconcile_interval: Duration::from_secs(5),
            handoff_deadline: Duration::from_secs(120),
            warming_deadline: Duration::from_secs(1800),
        }
    }
}

/// The per-phase cancellation budgets, bundled for every path that
/// judges handoff age (see `CoordinatorConfig::handoff_deadline` and
/// `warming_deadline`).
#[derive(Clone, Copy)]
struct PhaseDeadlines {
    handoff: Duration,
    warming: Duration,
}

impl CoordinatorConfig {
    fn phase_deadlines(&self) -> PhaseDeadlines {
        PhaseDeadlines {
            handoff: self.handoff_deadline,
            warming: self.warming_deadline,
        }
    }
}

pub struct Coordinator {
    store: Arc<PersonhogStore>,
    config: CoordinatorConfig,
    strategy: Arc<dyn AssignmentStrategy>,
    k8s_awareness: Option<Arc<K8sAwareness>>,
}

/// How long the election lease revoke may take before shutdown stops
/// waiting for it.
///
/// INVARIANT: one keepalive round's join plus this revoke must fit the
/// coordinator's graceful budget with room; the router's
/// `validate_lease_timescales` refuses a configuration that breaks it.
/// Deliberately not the pod's number — its budget differs, and matching
/// the two constants is what once put this one at its ceiling.
pub const REVOKE_TIMEOUT: Duration = Duration::from_secs(2);

/// How much of a paced wait the per-candidate offset may remove. Wide
/// enough to separate candidates that failed together, small enough that
/// the pace still restrains a wedged one.
const JITTER_FRACTION: f64 = 0.25;

/// A stable fraction in [0, 1) derived from a candidate's name. The
/// disturbances that end terms are shared, so the fleet must not walk
/// its ladders in lockstep — derived rather than random so the wait is
/// reproducible in a test.
fn jitter_offset(name: &str) -> f64 {
    let mut hasher = DefaultHasher::new();
    name.hash(&mut hasher);
    // Keep the 53 bits an f64 can hold exactly, so the ratio is a uniform
    // fraction rather than a rounded one.
    (hasher.finish() >> 11) as f64 / (1u64 << 53) as f64
}

/// Shorten a wait by this candidate's own offset.
///
/// Downward only, so a caller's own bound on the wait still holds after
/// jittering and no site needs a second clamp.
fn jittered(wait: Duration, name: &str) -> Duration {
    wait.mul_f64(1.0 - JITTER_FRACTION * jitter_offset(name))
}

/// The wait before campaigning again after a term ended badly, growing
/// while endings keep arriving. A free function so the invariant below
/// is checkable without a store.
///
/// Every bad ending shares this one pace — the etcd writes a campaign
/// spends are what it restrains. A candidate that could not observe the
/// election retries at the poll cadence instead, having spent only
/// reads.
///
/// INVARIANT: the wait never exceeds `leader_lease_ttl` — pacing past
/// it would make a candidate slower to take a free election than to
/// wait out a crashed leader's lease.
fn pace_after_ending(
    config: &CoordinatorConfig,
    consecutive: &mut u32,
    last: &mut Option<Instant>,
) -> Duration {
    let quiet = last.is_none_or(|at| at.elapsed() >= config.backoff_decay_window);
    *last = Some(Instant::now());
    *consecutive = if quiet {
        1
    } else {
        consecutive.saturating_add(1)
    };
    let cap = Duration::from_secs(config.leader_lease_ttl.max(0) as u64);
    let paced = config
        .run_retry_backoff
        .saturating_mul(2u32.saturating_pow(consecutive.saturating_sub(1)))
        .min(cap);
    jittered(paced, &config.name)
}

/// A cancellation this coordinator intends, and what to attribute it to
/// once it has landed.
///
/// Counted after the transaction rather than when the plan is built: a
/// concurrent coordinator can win the same partition, and counting at
/// intent attributes cancellations this coordinator never made — to
/// named routers, in the case of the missing-acker counter.
struct Cancellation {
    reason: &'static str,
    missing_ackers: Vec<String>,
}

impl Cancellation {
    fn record(&self) {
        counter!(
            "personhog_coordination_handoffs_cancelled_total",
            "reason" => self.reason,
        )
        .increment(1);
        for router in &self.missing_ackers {
            counter!(
                "personhog_coordination_freeze_ack_missing_total",
                "router" => router.clone(),
            )
            .increment(1);
        }
    }
}

/// A cancellation with no successor and no live owner to reaffirm
/// toward, applied as its own guarded transaction after the plan.
struct FallbackDelete {
    predecessor: HandoffState,
    mod_revision: i64,
    cancellation: Cancellation,
}

/// Why a standby stopped waiting on the leader-key watch.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Woke {
    /// The leader key was deleted: the election is open.
    Opened,
    /// The fallback interval elapsed; re-read in case the watch is
    /// stalled without having errored.
    Fallback,
    /// The stream ended or errored, so it can no longer be trusted.
    StreamLost,
}

/// What prompted a phase-advance evaluation. Only ack-triggered
/// evaluations record the ack-to-advance span: a departure or tick can
/// legitimately advance a handoff on acks that arrived long before, and
/// that elapsed time measures the blocker, not coordinator reaction.
#[derive(Clone, Copy, PartialEq, Eq)]
enum AdvanceTrigger {
    Ack,
    Other,
}

impl Coordinator {
    pub fn new(
        store: Arc<PersonhogStore>,
        config: CoordinatorConfig,
        strategy: Arc<dyn AssignmentStrategy>,
        k8s_awareness: Option<Arc<K8sAwareness>>,
    ) -> Self {
        Self {
            store,
            config,
            strategy,
            k8s_awareness,
        }
    }

    /// Run the coordinator loop. Continuously attempts leader election;
    /// when elected, runs the coordination loop until leadership is lost
    /// or cancellation is requested.
    pub async fn run(&self, cancel: CancellationToken) {
        util::preregister_coordinator_metrics();
        // Paces retries only — nothing here escalates. It grows while
        // bad endings keep arriving and starts over after a quiet
        // window, so a wedged coordinator settles at the cap while an
        // isolated failure long after a bad spell still costs the base.
        let mut consecutive_endings = 0u32;
        let mut last_ending: Option<Instant> = None;
        loop {
            if cancel.is_cancelled() {
                return;
            }
            // Campaign only into an opening: a campaign costs etcd
            // writes whether or not it wins, and every standby pays it.
            let attempt = match self.await_election_opening(&cancel).await {
                Ok(()) if cancel.is_cancelled() => return,
                // Awaited to completion, never raced: dropping try_lead
                // mid-cleanup would strand the election lease until TTL
                // expiry. It observes `cancel` internally.
                Ok(()) => self.try_lead(cancel.clone()).await,
                // Not a failed term — this candidate held nothing — so
                // no ending pace and no run-failure sample; it retries
                // at the poll cadence, which is the load a healthy
                // standby already costs. Shutdown first: exit teardown
                // errors here before losing the race against `cancel`,
                // and counting that would put a sample on every
                // rollout.
                Err(_) if cancel.is_cancelled() => return,
                Err(e) => {
                    counter!("personhog_coordination_election_observation_failures_total")
                        .increment(1);
                    let wait = jittered(self.config.standby_poll_interval, &self.config.name);
                    tracing::warn!(
                        name = %self.config.name,
                        error = %e,
                        wait = ?wait,
                        "could not observe the election; retrying"
                    );
                    if self.wait_or_shutdown(&cancel, wait).await {
                        return;
                    }
                    continue;
                }
            };
            match attempt {
                Ok(true) => {
                    tracing::info!(name = %self.config.name, "leadership ended normally");
                }
                Ok(false) => {}
                Err(e) if e.is_leadership_lost() => {
                    tracing::info!(name = %self.config.name, "abdicated; a successor takes over");
                    // Counted so a lease that cannot renew is visible as
                    // the flap it is.
                    counter!("personhog_coordination_abdications_total").increment(1);
                    // Paced like any other bad ending: try_lead revoked
                    // on the way out, so an unpaced retry flaps forever
                    // with no term long enough to move a handoff.
                    let wait = self.pace_after_ending(&mut consecutive_endings, &mut last_ending);
                    if self.wait_or_shutdown(&cancel, wait).await {
                        return;
                    }
                }
                Err(e) => {
                    let wait = self.pace_after_ending(&mut consecutive_endings, &mut last_ending);
                    util::record_run_failure(
                        "coordinator",
                        &self.config.name,
                        consecutive_endings,
                        &e,
                    );
                    if self.wait_or_shutdown(&cancel, wait).await {
                        return;
                    }
                }
            }
        }
    }

    /// This candidate's own [`pace_after_ending`], which carries the
    /// contract and the invariant.
    fn pace_after_ending(&self, consecutive: &mut u32, last: &mut Option<Instant>) -> Duration {
        pace_after_ending(&self.config, consecutive, last)
    }

    /// Wait, or report that shutdown arrived first.
    async fn wait_or_shutdown(&self, cancel: &CancellationToken, delay: Duration) -> bool {
        tokio::select! {
            _ = cancel.cancelled() => true,
            _ = tokio::time::sleep(delay) => false,
        }
    }

    /// Give up the election lease, bounded: unbounded, this cleanup
    /// waits out the very etcd outage that usually runs it, holding
    /// shutdown past the charts' grace. The lease expires on its TTL
    /// regardless.
    async fn revoke_election_lease(&self, lease_id: i64) -> Result<()> {
        tokio::time::timeout(REVOKE_TIMEOUT, self.store.revoke_lease(lease_id))
            .await
            .unwrap_or_else(|_| {
                tracing::warn!(
                    name = %self.config.name,
                    lease_id,
                    "election lease revoke timed out; it expires on its TTL"
                );
                Ok(())
            })
    }

    /// Block until this candidate has something to campaign for: no
    /// leader is recorded, or the one that is recorded goes away.
    /// Returns immediately on cancellation.
    ///
    /// Standing by costs one read and one idle watch per fallback
    /// interval, in place of a campaign per retry interval. The
    /// fallback re-read bounds the leaderless window whether the watch
    /// stalls or is lost, and a lost watch waits out its window before
    /// re-creating, so no failure mode costs more than the healthy
    /// cadence.
    pub async fn await_election_opening(&self, cancel: &CancellationToken) -> Result<()> {
        loop {
            // The revision this read returns anchors the watch, so a
            // leader that vanishes before the watch attaches is still
            // delivered. Both etcd calls race cancellation: unbounded,
            // each would outlive the shutdown budget against a dark
            // etcd.
            let read = tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                read = self.store.get_leader_with_revision() => read,
            };
            let (leader, revision) = read?;
            let Some(leader) = leader else {
                return Ok(());
            };
            tracing::debug!(
                name = %self.config.name,
                leader = %leader.holder,
                "another coordinator is leader, standing by"
            );

            let stream = tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                stream = self.store.watch_leader_from(revision + 1) => stream,
            };
            let mut stream = stream?;
            // A deadline for the whole wait: per-message construction
            // would restart it on every response and bound nothing.
            let fallback_at = tokio::time::Instant::now() + self.config.standby_poll_interval;
            let woke = loop {
                let message = tokio::select! {
                    _ = cancel.cancelled() => return Ok(()),
                    _ = tokio::time::sleep_until(fallback_at) => break Woke::Fallback,
                    message = stream.message() => message,
                };
                // A stream that ends or errors leaves this candidate
                // blind, so re-read rather than trusting it further.
                let response = match message {
                    Ok(Some(response)) => response,
                    Ok(None) => {
                        tracing::debug!(
                            name = %self.config.name,
                            "leader watch stream ended; re-reading"
                        );
                        break Woke::StreamLost;
                    }
                    Err(e) => {
                        tracing::debug!(
                            name = %self.config.name,
                            error = %e,
                            "leader watch stream failed; re-reading"
                        );
                        break Woke::StreamLost;
                    }
                };
                // etcd cancels a watcher with an ordinary response and
                // delivers nothing after it; awaiting further would
                // look idle rather than blind.
                if response.canceled() {
                    tracing::debug!(
                        name = %self.config.name,
                        reason = response.cancel_reason(),
                        compact_revision = response.compact_revision(),
                        "leader watch cancelled by etcd; re-reading"
                    );
                    break Woke::StreamLost;
                }
                if response
                    .events()
                    .iter()
                    .any(|event| event.event_type() == EventType::Delete)
                {
                    break Woke::Opened;
                }
            };
            match woke {
                Woke::Opened => return Ok(()),
                // The fallback re-read: loop to a fresh look and a
                // fresh watch.
                Woke::Fallback => {}
                Woke::StreamLost => {
                    // Shutdown first, as at the run-level arm: exit
                    // teardown errors the stream before the cancel race
                    // resolves, and counting it would sample every
                    // rollout.
                    if cancel.is_cancelled() {
                        return Ok(());
                    }
                    // Counted: without a series, a flapping etcd is
                    // indistinguishable from a healthy fleet.
                    counter!("personhog_coordination_election_watch_interruptions_total")
                        .increment(1);
                    // Wait out the window before re-creating, so a
                    // flapping watcher costs the healthy cadence — one
                    // read and one create per interval — and never more.
                    tokio::select! {
                        _ = cancel.cancelled() => return Ok(()),
                        _ = tokio::time::sleep_until(fallback_at) => {}
                    }
                }
            }
        }
    }

    /// One leadership attempt; returns whether this candidate actually
    /// led. Always runs its cleanup — keepalive shutdown and election
    /// lease revoke — before returning, so a graceful exit frees the
    /// election immediately instead of stranding it until TTL expiry.
    /// `run` relies on that by awaiting this call to completion.
    async fn try_lead(&self, cancel: CancellationToken) -> Result<bool> {
        // Every campaign costs etcd a lease grant, a transaction and,
        // when it loses, a revoke. Against wins, this is what says
        // whether the fleet is electing or merely polling.
        counter!("personhog_coordination_election_campaigns_total").increment(1);
        let granted_at = Instant::now();
        // Both campaign calls race cancellation, or a hanging etcd
        // holds shutdown past the graceful budget. A grant abandoned
        // mid-flight leaves a lease nothing hangs off; it expires on
        // its TTL.
        let lease_id = tokio::select! {
            _ = cancel.cancelled() => return Ok(false),
            granted = self.store.grant_lease(self.config.leader_lease_ttl) => granted?,
        };

        let acquired = tokio::select! {
            // The CAS may still land server-side after this arm wins;
            // the revoke tears the lease down, and the key is
            // lease-bound, so either way nothing outlives shutdown
            // longer than the TTL.
            _ = cancel.cancelled() => {
                drop(self.revoke_election_lease(lease_id).await);
                return Ok(false);
            }
            acquired = self.store.try_acquire_leadership(&self.config.name, lease_id) => {
                match acquired {
                    Ok(acquired) => acquired,
                    Err(e) => {
                        drop(self.revoke_election_lease(lease_id).await);
                        return Err(e);
                    }
                }
            }
        };

        if !acquired {
            tracing::debug!(name = %self.config.name, "another coordinator is leader, standing by");
            // Nothing hangs off the lease; revoke it rather than leaking
            // one lease per election retry from every standby candidate.
            drop(self.revoke_election_lease(lease_id).await);
            return Ok(false);
        }

        tracing::info!(name = %self.config.name, "acquired leadership");
        gauge!("personhog_coordination_is_coordinator").set(1.0);
        counter!("personhog_coordination_elections_won_total").increment(1);

        // A failed keepalive means the lease is gone (or about to be) and
        // another candidate can win the election: abdicate rather than
        // keep coordinating as a zombie alongside the successor. The
        // successor's bootstrap reconciles in-flight state, and handoff
        // transitions are CAS-guarded against exactly this overlap.
        let keepalive_cancel = cancel.child_token();
        let lease_lost = CancellationToken::new();
        let keepalive_handle = {
            let store = Arc::clone(&self.store);
            let interval = self.config.keepalive_interval;
            let lease_ttl = self.config.leader_lease_ttl;
            let token = keepalive_cancel.clone();
            let lease_lost = lease_lost.clone();
            tokio::spawn(async move {
                // The keepalive runs as its own inner task so a panic
                // surfaces as a JoinError here instead of silently
                // unwinding this watcher: a leader whose keepalive died
                // without signalling would coordinate on with no renewal
                // until a successor is elected alongside it.
                let inner = tokio::spawn(util::run_lease_keepalive(
                    store,
                    lease_id,
                    interval,
                    lease_ttl,
                    granted_at,
                    "coordinator",
                    // The coordinator serves no partition data; there is
                    // no request path to gate on its lease.
                    None,
                    token.clone(),
                ));
                let failure = match inner.await {
                    Ok(Ok(())) => (!token.is_cancelled())
                        .then(|| "election lease keepalive exited unexpectedly".to_string()),
                    Ok(Err(e)) => Some(format!("election lease keepalive failed: {e}")),
                    Err(join_err) => Some(format!("election lease keepalive panicked: {join_err}")),
                };
                if let Some(reason) = failure {
                    if !token.is_cancelled() {
                        tracing::error!(reason, "abdicating leadership");
                        lease_lost.cancel();
                    }
                }
            })
        };

        let result = tokio::select! {
            // Raced here as well: the loop's bootstrap is a run of
            // unbounded store calls before its first select, and the
            // keepalive cannot preempt them on a graceful exit (its
            // token is a child of `cancel`, so `lease_lost` never
            // fires). Dropping the loop mid-bootstrap is safe — every
            // downstream effect is idempotent — and the teardown below
            // still runs, which is what spares the successor the TTL.
            _ = cancel.cancelled() => Ok(()),
            _ = lease_lost.cancelled() => Err(Error::leadership_lost()),
            result = self.run_coordination_loop(cancel.clone()) => result,
        };

        // Clean up keepalive
        keepalive_cancel.cancel();
        drop(keepalive_handle.await);

        // Revoke so the next candidate's campaign wins immediately instead
        // of waiting out the lease TTL.
        drop(self.revoke_election_lease(lease_id).await);

        reset_coordinator_gauges();

        result.map(|()| true)
    }

    async fn run_coordination_loop(&self, cancel: CancellationToken) -> Result<()> {
        // Anchor every watch to one revision taken BEFORE bootstrap, so
        // an ack written while a watch is still attaching is delivered
        // rather than missed. Bootstrap reads may double-observe what
        // the watches also deliver; all downstream work is idempotent.
        let anchor = self.store.current_revision().await? + 1;
        let pods_stream = self.store.watch_pods_from(anchor).await?;
        let handoffs_stream = self.store.watch_handoffs_from(anchor).await?;
        let freeze_acks_stream = self.store.watch_freeze_acks_from(anchor).await?;
        let drained_acks_stream = self.store.watch_drained_acks_from(anchor).await?;
        let warmed_acks_stream = self.store.watch_warmed_acks_from(anchor).await?;
        let routers_stream = self.store.watch_routers_from(anchor).await?;

        let mut tasks = tokio::task::JoinSet::new();

        // Wakes the planning loop for state changes only the coordinator
        // itself produces — a deadline cancellation deletes a handoff,
        // which fires no pod event, so without an explicit wake no
        // re-plan would run until the next unrelated pod change. Waking
        // the one planning loop rather than planning inline keeps a
        // single planner task; `Notify` stores a permit, so a wake fired
        // mid-plan is picked up on the next iteration rather than lost.
        let replan = Arc::new(Notify::new());

        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let k8s_awareness = self.k8s_awareness.clone();
            let debounce_interval = self.config.rebalance_debounce_interval;
            let deadlines = self.config.phase_deadlines();
            let replan = Arc::clone(&replan);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_pods_loop(
                    store,
                    strategy,
                    k8s_awareness,
                    debounce_interval,
                    deadlines,
                    replan,
                    token,
                    pods_stream,
                )
                .await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let k8s_awareness = self.k8s_awareness.clone();
            let deadlines = self.config.phase_deadlines();
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_handoffs_loop(
                    store,
                    strategy,
                    k8s_awareness,
                    deadlines,
                    token,
                    handoffs_stream,
                )
                .await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::run_ack_watch("freeze", freeze_acks_stream, &store, token).await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::run_ack_watch("drained", drained_acks_stream, &store, token).await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::run_ack_watch("warmed", warmed_acks_stream, &store, token).await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::run_router_departure_watch(routers_stream, &store, token).await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let interval = self.config.reconcile_interval;
            let replan = Arc::clone(&replan);
            let token = cancel.child_token();
            tasks.spawn(
                async move { Self::reconcile_tick_loop(store, interval, replan, token).await },
            );
        }

        // Reconcile any handoffs that already have full ack quorum.
        // This handles acks that arrived before this coordinator took leadership.
        self.reconcile_pending_handoffs().await?;

        // Compute initial assignments for any pods that are already registered
        self.handle_pod_change().await?;

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

    #[allow(clippy::too_many_arguments)]
    async fn watch_pods_loop(
        store: Arc<PersonhogStore>,
        strategy: Arc<dyn AssignmentStrategy>,
        k8s_awareness: Option<Arc<K8sAwareness>>,
        debounce_interval: Duration,
        deadlines: PhaseDeadlines,
        replan: Arc<Notify>,
        cancel: CancellationToken,
        mut stream: WatchStream,
    ) -> Result<()> {
        loop {
            // Wait for the first pod event, or an explicit re-plan wake
            // (a deadline cancellation deletes a handoff, which fires no
            // pod event but leaves the placement short of desired).
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = replan.notified() => {}
                msg = stream.message() => {
                    let resp = util::live_watch_response(msg?, "pod")?;
                    Self::log_pod_events(&resp);
                }
            }

            // Drain additional events arriving within the debounce window
            let deadline = tokio::time::Instant::now() + debounce_interval;
            loop {
                tokio::select! {
                    _ = cancel.cancelled() => return Ok(()),
                    _ = tokio::time::sleep_until(deadline) => break,
                    msg = stream.message() => {
                        let resp = util::live_watch_response(msg?, "pod")?;
                        Self::log_pod_events(&resp);
                    }
                }
            }

            Self::handle_pod_change_static(
                &store,
                strategy.as_ref(),
                k8s_awareness.as_deref(),
                deadlines,
            )
            .await?;
        }
    }

    fn log_pod_events(resp: &etcd_client::WatchResponse) {
        for event in resp.events() {
            match event.event_type() {
                EventType::Put => tracing::info!("pod registered or updated"),
                EventType::Delete => tracing::warn!("pod lease expired or deleted"),
            }
        }
    }

    async fn watch_handoffs_loop(
        store: Arc<PersonhogStore>,
        strategy: Arc<dyn AssignmentStrategy>,
        k8s_awareness: Option<Arc<K8sAwareness>>,
        deadlines: PhaseDeadlines,
        cancel: CancellationToken,
        mut stream: WatchStream,
    ) -> Result<()> {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = util::live_watch_response(msg?, "handoff")?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            match parse_watch_value::<HandoffState>(event) {
                                Ok(handoff) => {
                                    Self::handle_handoff_update_static(&store, &handoff).await?;
                                    // Initial / dead-old-owner handoffs can
                                    // satisfy their Freezing → Warming
                                    // preconditions at creation time (no
                                    // drain needed, vacuous router quorum).
                                    // Nudge advancement here so they don't
                                    // stall waiting for an ack event that
                                    // will never arrive.
                                    Self::check_phase_advance(&store, handoff.partition, AdvanceTrigger::Other).await?;
                                }
                                Err(e) => {
                                    tracing::error!(error = %e, "failed to parse handoff event");
                                }
                            }
                        }
                    }

                    // After processing all events in this batch, check if all
                    // handoffs have completed. If so, re-trigger rebalancing as
                    // the final sweep for moves that were pinned while these
                    // handoffs were in flight (pod changes themselves are never
                    // deferred; they plan around the in-flight set).
                    if store.list_handoffs().await?.is_empty() {
                        Self::handle_pod_change_static(
                            &store,
                            strategy.as_ref(),
                            k8s_awareness.as_deref(),
                            deadlines,
                        )
                        .await?;
                    }
                }
            }
        }
    }

    /// Consume an ack watch stream (freeze, drained, or warmed), nudging
    /// phase advancement for the acked partition on every event.
    async fn run_ack_watch(
        kind: &str,
        mut stream: WatchStream,
        store: &PersonhogStore,
        cancel: CancellationToken,
    ) -> Result<()> {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = util::live_watch_response(msg?, kind)?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            let partition = event.kv().and_then(|kv| {
                                let key = from_utf8(kv.key()).ok()?;
                                store::extract_partition_from_ack_key(key)
                            });

                            if let Some(partition) = partition {
                                Self::check_phase_advance(store, partition, AdvanceTrigger::Ack).await?;
                            }
                        }
                    }
                }
            }
        }
    }

    /// React to router departures, which can newly satisfy every
    /// in-flight freeze's quorum and fire no other event. Puts are
    /// ignored: a router joining after a handoff's creation never
    /// enters its quorum.
    async fn run_router_departure_watch(
        mut stream: WatchStream,
        store: &PersonhogStore,
        cancel: CancellationToken,
    ) -> Result<()> {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = util::live_watch_response(msg?, "router")?;
                    let departed = resp
                        .events()
                        .iter()
                        .any(|e| e.event_type() == EventType::Delete);
                    if departed {
                        for handoff in store.list_handoffs().await? {
                            Self::check_phase_advance(store, handoff.partition, AdvanceTrigger::Other).await?;
                        }
                    }
                }
            }
        }
    }

    /// Periodically re-evaluate every in-flight handoff, mirroring what
    /// the ack and router-departure watches do on events. This is the
    /// liveness backstop for anything the watches miss — a dropped
    /// stream, an event lost in a coordinator failover window. All the
    /// work it drives is idempotent: phase transitions use CAS and
    /// completed-handoff cleanup tolerates already-deleted records.
    async fn reconcile_tick_loop(
        store: Arc<PersonhogStore>,
        interval: Duration,
        replan: Arc<Notify>,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut tick = tokio::time::interval(interval);
        // As the pod's and router's passes do. The default replays every
        // missed tick back to back, which would fire this body's read
        // fan-out — one pass per in-flight handoff — in a tight loop
        // exactly when etcd is too slow to have kept up with it.
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tick.tick() => {
                    // INVARIANT: listed before the handoffs — a
                    // membership written after this read is not a
                    // candidate, so the sweep cannot collect a record a
                    // newer handoff refers to.
                    let quorum_candidates = store.list_freeze_quorum_ids().await;
                    let handoffs = store.list_handoffs().await?;
                    for handoff in &handoffs {
                        Self::handle_handoff_update_static(&store, handoff).await?;
                        Self::check_phase_advance(&store, handoff.partition, AdvanceTrigger::Other)
                            .await?;
                    }
                    // Advancement first, planning second: a handoff that
                    // can still progress gets every chance to before the
                    // planner judges it. The wake is unconditional —
                    // level-triggered planning, exactly as the stateright
                    // model assumes (its Rebalance action is enabled in
                    // every state). The planner is cheap when there is
                    // nothing to do, and an unconditional wake is what
                    // catches the events no watch delivers: a pod
                    // registration lost to a dropped stream, a doomed
                    // handoff whose trigger event never arrived, placement
                    // drift of any cause. Cancellation itself is a
                    // planning decision — the planner replaces a doomed
                    // handoff with whatever resolves its stashes.
                    replan.notify_one();
                    // The gauge refresh is best-effort and runs after the
                    // reconcile pass: its reads exist only for metrics and
                    // must never delay or interrupt handoff advancement.
                    // A skipped refresh is repaired by the next tick.
                    let pods = store.list_pods().await;
                    let routers = store.list_routers().await;
                    match (pods, routers) {
                        (Ok(pods), Ok(routers)) => {
                            record_cluster_gauges(&handoffs, &pods, routers.len());
                        }
                        (Err(e), _) | (_, Err(e)) => {
                            tracing::debug!(error = %e, "skipping cluster gauge refresh");
                        }
                    }
                    // Last, with the gauge refresh, because it is
                    // housekeeping by the same standard: only its two
                    // reads above need their order, while its deletes
                    // are a round trip per orphan that a read-only etcd
                    // would otherwise charge ahead of every handoff and
                    // the planner wake.
                    Self::collect_stale_freeze_quorums(&store, quorum_candidates, &handoffs).await;
                }
            }
        }
    }

    /// Delete the freeze-quorum records no live handoff refers to.
    /// Housekeeping without a transaction: a record left behind costs
    /// kilobytes until the next tick, and one deleted in error only
    /// makes its handoff fall back to requiring every live router —
    /// neither can advance a handoff early. A wrong delete surfaces in
    /// `unresolved_freeze_quorums_total` only from a process that has
    /// to read; a cached coordinator neutralizes it silently.
    async fn collect_stale_freeze_quorums(
        store: &PersonhogStore,
        candidates: Result<Vec<String>>,
        handoffs: &[HandoffState],
    ) {
        let candidates = match candidates {
            Ok(ids) => ids,
            Err(e) => {
                // Counted: a sweep that never runs is otherwise
                // indistinguishable from one with nothing to collect.
                counter!(
                    "personhog_coordination_freeze_quorum_sweep_failures_total",
                    "stage" => "list"
                )
                .increment(1);
                tracing::debug!(error = %e, "skipping freeze quorum sweep");
                return;
            }
        };
        let referenced: HashSet<&str> = handoffs
            .iter()
            .filter_map(|h| h.freeze_quorum_ref.as_deref())
            .collect();
        for id in candidates
            .iter()
            .filter(|id| !referenced.contains(id.as_str()))
        {
            match store.delete_freeze_quorum(id).await {
                Ok(()) => {
                    // The cheap half of the sweep's observability: a
                    // rate here that outpaces plan creation is the shape
                    // a sweep collecting records it should have spared
                    // would take.
                    counter!("personhog_coordination_freeze_quorums_collected_total").increment(1);
                    tracing::debug!(quorum_id = %id, "collected unreferenced freeze quorum");
                }
                Err(e) => {
                    // Counted, not only logged: the router runs at INFO,
                    // so a sweep whose every delete fails is otherwise
                    // silent while its backlog grows one record per plan.
                    counter!(
                        "personhog_coordination_freeze_quorum_sweep_failures_total",
                        "stage" => "delete"
                    )
                    .increment(1);
                    tracing::debug!(quorum_id = %id, error = %e, "freeze quorum sweep failed")
                }
            }
        }
    }

    /// Advance a handoff's phase when its current phase's preconditions are satisfied:
    ///   Freezing -> Draining: all registered routers have FreezeAck
    ///   Draining -> Warming:  old owner has DrainedAck (or old owner is gone)
    ///   Warming  -> Complete: new owner has WarmedAck (atomic with assignment write)
    ///
    /// The Freezing/Draining split sequences router-stop before old-owner-drain so
    /// that "no inflight handlers" actually means "no producer can append more
    /// to Kafka." Without the split, a slow router could send a final write
    /// to the old owner after the old owner observed inflight=0 momentarily
    /// and wrote DrainedAck, advancing HWM past the point warming snapshots.
    ///
    /// Called whenever an ack key is observed. Safe to call spuriously: reads
    /// are idempotent and transitions use CAS.
    async fn check_phase_advance(
        store: &PersonhogStore,
        partition: u32,
        trigger: AdvanceTrigger,
    ) -> Result<()> {
        let handoff = match store.get_handoff(partition).await? {
            Some(h) => h,
            None => return Ok(()),
        };

        match handoff.phase {
            HandoffPhase::Freezing => {
                let routers = store.list_routers().await?;
                let freeze_acks = store.list_freeze_acks(partition).await?;
                let quorum = store.resolve_freeze_quorum(&handoff).await?;

                // Quorum semantics live in `protocol::freeze_quorum_met`
                // (shared with the stateright model).
                if freeze_quorum_met(&routers, &freeze_acks, &handoff, quorum.as_deref()) {
                    // Initial assignments (no old owner) skip Draining
                    // entirely — there's no inflight to wait for. Advance
                    // straight to Warming.
                    let target = match handoff.old_owner {
                        None => HandoffPhase::Warming,
                        Some(_) => HandoffPhase::Draining,
                    };
                    let advanced = store
                        .cas_handoff_phase(
                            partition,
                            &handoff.handoff_id,
                            HandoffPhase::Freezing,
                            target,
                        )
                        .await?;
                    if advanced {
                        record_phase_advance(&handoff, target);
                        if trigger == AdvanceTrigger::Ack {
                            util::record_ack_to_advance(
                                "freezing",
                                freeze_acks.iter().map(|a| a.acked_at_ms),
                            );
                        }
                        tracing::info!(
                            partition,
                            freeze_acks = freeze_acks.len(),
                            routers = routers.len(),
                            old_owner = ?handoff.old_owner,
                            ?target,
                            "freeze quorum reached, advanced from Freezing"
                        );
                    }
                } else {
                    // Evaluations are event-driven (acks, router
                    // departures, the reconcile tick), so this names the
                    // blocker a handful of times per stalled handoff
                    // rather than spamming.
                    tracing::info!(
                        partition,
                        handoff_id = %handoff.handoff_id,
                        missing_freeze_ackers = ?missing_freeze_ackers(
                            &routers,
                            &freeze_acks,
                            &handoff,
                            quorum.as_deref()
                        ),
                        "freeze quorum not yet met"
                    );
                }
            }
            HandoffPhase::Draining => {
                // Drain semantics live in `protocol::drain_satisfied`
                // (shared with the stateright model).
                let pods = store.list_pods().await?;
                let drained_acks = store.list_drained_acks(partition).await?;
                if drain_satisfied(&pods, &drained_acks, &handoff) {
                    let advanced = store
                        .cas_handoff_phase(
                            partition,
                            &handoff.handoff_id,
                            HandoffPhase::Draining,
                            HandoffPhase::Warming,
                        )
                        .await?;
                    if advanced {
                        record_phase_advance(&handoff, HandoffPhase::Warming);
                        if trigger == AdvanceTrigger::Ack {
                            util::record_ack_to_advance(
                                "draining",
                                drained_acks.iter().map(|a| a.acked_at_ms),
                            );
                        }
                        tracing::info!(
                            partition,
                            old_owner = ?handoff.old_owner,
                            "old owner drained, advanced to Warming"
                        );
                    }
                }
            }
            HandoffPhase::Warming => {
                let warmed = store.list_warmed_acks(partition).await?;
                if warm_satisfied(&warmed, &handoff) {
                    tracing::info!(
                        partition,
                        new_owner = %handoff.new_owner,
                        "new owner warmed, completing handoff"
                    );
                    match store
                        .complete_handoff(partition, &handoff.handoff_id, HandoffPhase::Warming)
                        .await
                    {
                        Ok(true) => {
                            record_phase_advance(&handoff, HandoffPhase::Complete);
                            if trigger == AdvanceTrigger::Ack {
                                util::record_ack_to_advance(
                                    "warming",
                                    warmed.iter().map(|a| a.acked_at_ms),
                                );
                            }
                        }
                        Ok(false) => {
                            tracing::warn!(partition, "handoff modified concurrently, skipping");
                        }
                        Err(Error::NotFound(_)) => {
                            tracing::warn!(partition, "handoff already deleted, ignoring");
                        }
                        Err(e) => return Err(e),
                    }
                }
            }
            HandoffPhase::Complete => {
                // Terminal; nothing to do. watch_handoffs_loop will clean up.
            }
        }

        Ok(())
    }

    /// Reconcile pre-existing handoffs on coordinator startup or leadership
    /// change. Handles three cases:
    ///   - Handoffs already in Complete: clean up the records the prior
    ///     coordinator wrote but didn't get to delete (their cleanup runs in
    ///     watch_handoffs_loop, which the new coordinator missed).
    ///   - Handoffs whose preconditions are already met: nudge them forward.
    ///   - Handoffs still in flight: leave alone; watches will drive them.
    async fn reconcile_pending_handoffs(&self) -> Result<()> {
        let handoffs = self.store.list_handoffs().await?;
        if handoffs.is_empty() {
            return Ok(());
        }

        tracing::info!(
            count = handoffs.len(),
            "reconciling existing handoffs on startup"
        );

        for handoff in &handoffs {
            // Complete handoffs need their cleanup applied directly — the
            // watch_handoffs_loop's Put-driven path won't replay them.
            Self::handle_handoff_update_static(&self.store, handoff).await?;
            // Non-terminal handoffs may have their preconditions already met.
            Self::check_phase_advance(&self.store, handoff.partition, AdvanceTrigger::Other)
                .await?;
        }

        Ok(())
    }

    /// Handle a pod registration/deletion by recomputing assignments.
    async fn handle_pod_change(&self) -> Result<()> {
        Self::handle_pod_change_static(
            &self.store,
            self.strategy.as_ref(),
            self.k8s_awareness.as_deref(),
            self.config.phase_deadlines(),
        )
        .await
    }

    async fn handle_pod_change_static(
        store: &PersonhogStore,
        strategy: &dyn AssignmentStrategy,
        k8s_awareness: Option<&K8sAwareness>,
        deadlines: PhaseDeadlines,
    ) -> Result<()> {
        let pods = store.list_pods().await?;
        let total_partitions = match store.get_total_partitions().await {
            Ok(n) => n,
            Err(Error::NotFound(_)) => {
                tracing::debug!("total_partitions not set, skipping assignment");
                return Ok(());
            }
            Err(e) => return Err(e),
        };

        // K8s-aware placement policies for smarter rebalancing
        let members = match k8s_awareness {
            Some(k8s) => members_for_k8s(k8s, &pods, total_partitions).await,
            None => Member::active_all(&active_pod_names(&pods)),
        };

        // Classify the in-flight handoffs. One whose new owner's
        // registration is gone can never advance (no WarmedAck will ever
        // arrive); one that has outstayed its phase's deadline is wedged
        // on an acknowledgement that is not coming. Both are cancelled by
        // this pass — never by deletion, but by atomic replacement with
        // whatever resolves their stashes, decided once the plan is
        // known. A dead *old* owner is deliberately not a trigger:
        // Freezing waits on routers, an absent old owner in Draining is
        // vacuously drained, and such handoffs advance on their own —
        // cancelling them would tear down a healthy in-flight warm.
        // Everything else pins its partition: the plan excludes it and
        // attributes it to its target, so a stuck handoff defers only
        // its own partition.
        let in_flight = store.list_handoffs_with_mod_revisions().await?;
        let registered: HashSet<&str> = pods.iter().map(|p| p.pod_name.as_str()).collect();
        let now_ms = util::now_millis();
        let (cancelled, pinned): (Vec<_>, Vec<_>) = in_flight.into_iter().partition(|(h, _)| {
            h.phase != HandoffPhase::Complete
                && (!registered.contains(h.new_owner.as_str())
                    || past_phase_deadline(h, now_ms, deadlines.handoff, deadlines.warming))
        });
        let pinned: Vec<HandoffState> = pinned.into_iter().map(|(h, _)| h).collect();
        if !pinned.is_empty() {
            tracing::info!(pinned = pinned.len(), "planning around in-flight handoffs");
        }

        // One revisioned snapshot feeds both the placement computation and
        // the apply-time preconditions: a handoff's old_owner is only
        // meaningful while the assignment it was read from is unchanged.
        let current_assignments = store.list_assignments_with_mod_revisions().await?;

        let current_map: HashMap<u32, String> = current_assignments
            .iter()
            .map(|(a, _)| (a.partition, a.owner.clone()))
            .collect();
        let assignment_revisions: HashMap<u32, i64> = current_assignments
            .iter()
            .map(|(a, revision)| (a.partition, *revision))
            .collect();

        // Placement and diff semantics (moves carry the prior owner, fresh
        // partitions carry none, everything goes through Freezing) live in
        // `protocol::plan_partial_rebalance`, shared with the stateright
        // model. Cancelled partitions are deliberately not pinned: the
        // plan is free to place them, and whatever it decides becomes
        // their replacement below.
        let plan =
            plan_partial_rebalance(strategy, &current_map, &pinned, &members, total_partitions);

        if plan.handoffs.is_empty() && cancelled.is_empty() {
            tracing::debug!("no handoffs needed");
            return Ok(());
        }

        // Snapshot the routers that must ack these freezes. Read here,
        // once, rather than per-check: the whole point is that the
        // requirement is fixed at creation and cannot grow as routers
        // come and go (see `HandoffState::freeze_quorum`).
        let routers = store.list_routers().await?;
        let freeze_quorum: Vec<String> = routers.iter().map(|r| r.router_name.clone()).collect();
        // One record for the whole plan: the membership is the same for
        // every handoff it creates, and inlining it per handoff is what
        // made a large plan exceed etcd's maximum request size.
        let freeze_quorum_id = util::new_handoff_id();

        let now = util::now_seconds();
        let handoff_objects: Vec<HandoffState> = plan
            .handoffs
            .iter()
            .map(|h| HandoffState {
                partition: h.partition,
                old_owner: h.old_owner.clone(),
                new_owner: h.new_owner.clone(),
                new_owner_address: pods
                    .iter()
                    .find(|p| p.pod_name == h.new_owner)
                    .and_then(|p| p.advertise_address.clone()),
                phase: HandoffPhase::Freezing,
                started_at: now,
                handoff_id: util::new_handoff_id(),
                freeze_quorum: None,
                freeze_quorum_ref: Some(freeze_quorum_id.clone()),
                created_at_ms: now_ms,
                phase_entered_at_ms: now_ms,
            })
            .collect();

        // Disposition for every cancelled handoff, in one pass over the
        // plan. A cancelled partition the plan re-placed gets its
        // successor as an atomic replacement — routers keep stashing
        // without ever observing a gap. One the plan left alone resolves
        // to its live current owner as a reaffirm: `Complete` toward that
        // owner, which drains stashes home through the routers' ordinary
        // Complete handling and converges the owner pod back to serving.
        // (`old_owner` stays `None` on a reaffirm — naming the owner on
        // both sides would match `desired_state`'s old-owner arm first
        // and make the pod release the partition instead of resuming.)
        // Only when neither exists — owner dead, nothing placeable — is
        // the record deleted outright, which is safe fail-closed: with no
        // live owner there is no one to drain to, and rejected requests
        // surface as retryable errors rather than lost writes.
        let mut cancelled_by_partition: HashMap<u32, (HandoffState, i64)> = cancelled
            .into_iter()
            .map(|(h, rev)| (h.partition, (h, rev)))
            .collect();
        let mut creations: Vec<HandoffState> = Vec::new();
        let mut replacements: Vec<HandoffReplacement> = Vec::new();
        let mut fallback_deletes: Vec<FallbackDelete> = Vec::new();
        let mut replaced_dispositions: Vec<&'static str> = Vec::new();
        // Held until the plan transaction lands; see `Cancellation`.
        let mut planned_cancellations: Vec<Cancellation> = Vec::new();

        for handoff in handoff_objects {
            match cancelled_by_partition.remove(&handoff.partition) {
                Some((predecessor, mod_revision)) => {
                    planned_cancellations.push(
                        Self::describe_cancellation(
                            store,
                            &routers,
                            &predecessor,
                            &registered,
                            "successor",
                        )
                        .await,
                    );
                    replacements.push(HandoffReplacement {
                        handoff,
                        expected_mod_revision: mod_revision,
                    });
                    replaced_dispositions.push("successor");
                }
                None => creations.push(handoff),
            }
        }
        for (predecessor, mod_revision) in cancelled_by_partition.into_values() {
            let owner = current_map
                .get(&predecessor.partition)
                .filter(|owner| registered.contains(owner.as_str()));
            match owner {
                Some(owner) => {
                    planned_cancellations.push(
                        Self::describe_cancellation(
                            store,
                            &routers,
                            &predecessor,
                            &registered,
                            "reaffirm",
                        )
                        .await,
                    );
                    replacements.push(HandoffReplacement {
                        handoff: HandoffState {
                            partition: predecessor.partition,
                            old_owner: None,
                            new_owner: owner.clone(),
                            new_owner_address: pods
                                .iter()
                                .find(|p| &p.pod_name == owner)
                                .and_then(|p| p.advertise_address.clone()),
                            phase: HandoffPhase::Complete,
                            started_at: now,
                            handoff_id: util::new_handoff_id(),
                            // A reaffirm requires no acks at all, which
                            // an empty membership states directly — no
                            // record to resolve, and never the legacy
                            // fallback.
                            freeze_quorum: Some(Vec::new()),
                            freeze_quorum_ref: None,
                            created_at_ms: now_ms,
                            phase_entered_at_ms: now_ms,
                        },
                        expected_mod_revision: mod_revision,
                    });
                    replaced_dispositions.push("reaffirm");
                }
                None => {
                    let cancellation = Self::describe_cancellation(
                        store,
                        &routers,
                        &predecessor,
                        &registered,
                        "delete",
                    )
                    .await;
                    fallback_deletes.push(FallbackDelete {
                        predecessor,
                        mod_revision,
                        cancellation,
                    });
                }
            }
        }

        let moves = creations
            .iter()
            .chain(replacements.iter().map(|r| &r.handoff))
            .filter(|h| h.phase == HandoffPhase::Freezing && h.old_owner.is_some())
            .count();
        let freezing_total = creations.len()
            + replacements
                .iter()
                .filter(|r| r.handoff.phase == HandoffPhase::Freezing)
                .count();
        tracing::info!(
            reassignments = moves,
            fresh = freezing_total - moves,
            replaced = replacements.len(),
            "creating handoffs"
        );

        // The rebalance writes no assignment records: handoff completion is
        // the sole writer of assignments (see `complete_handoff`'s
        // invariant), so routers always observe owner changes as Complete
        // events, and a stale plan can never restore a superseded owner.
        // Each handoff instead carries a precondition tying it to the
        // snapshot its old_owner came from.
        let preconditions: Vec<AssignmentPrecondition> = creations
            .iter()
            .chain(replacements.iter().map(|r| &r.handoff))
            .map(|h| match assignment_revisions.get(&h.partition) {
                Some(&mod_revision) => AssignmentPrecondition::UnchangedSince {
                    partition: h.partition,
                    mod_revision,
                },
                None => AssignmentPrecondition::Absent {
                    partition: h.partition,
                },
            })
            .collect();

        let references_quorum = creations
            .iter()
            .chain(replacements.iter().map(|r| &r.handoff))
            .any(|handoff| handoff.freeze_quorum_ref.is_some());
        if (!creations.is_empty() || !replacements.is_empty())
            && !store
                .apply_plan(
                    &[],
                    &creations,
                    &replacements,
                    &preconditions,
                    // A plan whose cancellations all resolve to reaffirms
                    // creates no handoff that refers to a membership, and
                    // that is the common shape when a wedged freeze had
                    // sound placement. Writing one anyway leaves a record
                    // for the next sweep to delete, during the mass
                    // cancellation when etcd is least well.
                    references_quorum.then_some((&freeze_quorum_id, &freeze_quorum)),
                )
                .await?
        {
            // A concurrent invocation (the empty-set re-trigger racing a
            // pod event, or a failing-over coordinator) created a handoff
            // first. Its plan acted on fresher state than ours; whatever
            // this plan wanted beyond it is replanned by the next pod
            // event or the final sweep.
            tracing::info!("concurrent plan won handoff creation; standing down");
            return Ok(());
        }
        for handoff in creations
            .iter()
            .chain(replacements.iter().map(|r| &r.handoff))
        {
            tracing::info!(
                partition = handoff.partition,
                handoff_id = %handoff.handoff_id,
                old_owner = ?handoff.old_owner,
                new_owner = %handoff.new_owner,
                phase = ?handoff.phase,
                "handoff created"
            );
        }
        for cancellation in &planned_cancellations {
            cancellation.record();
        }
        for disposition in &replaced_dispositions {
            counter!(
                "personhog_coordination_handoffs_replaced_total",
                "disposition" => *disposition,
            )
            .increment(1);
        }

        // The fallback deletes are per-partition guarded transactions
        // outside the plan txn: each partition's disposition is atomic on
        // its own, which is what the safety argument needs, and a stale
        // guard only ever skips a cancel for a record that changed under
        // us.
        for delete in fallback_deletes {
            if store
                .delete_handoff_and_acks_if_unchanged(
                    delete.predecessor.partition,
                    delete.mod_revision,
                )
                .await?
            {
                delete.cancellation.record();
                counter!(
                    "personhog_coordination_handoffs_replaced_total",
                    "disposition" => "delete",
                )
                .increment(1);
            }
        }

        counter!("personhog_coordination_handoffs_created_total", "kind" => "move")
            .increment(moves as u64);
        counter!("personhog_coordination_handoffs_created_total", "kind" => "fresh")
            .increment((freezing_total - moves) as u64);

        // Nudge advancement for handoffs whose preconditions are already
        // satisfied at creation time (no old_owner, dead old_owner, vacuous
        // router quorum). Without this, such handoffs would stall waiting
        // for an ack event that will never arrive — the watch loop's nudge
        // only catches subsequent Put events.
        for handoff in creations
            .iter()
            .chain(replacements.iter().map(|r| &r.handoff))
        {
            Self::check_phase_advance(store, handoff.partition, AdvanceTrigger::Other).await?;
        }

        Ok(())
    }

    /// One log line per cancellation, error-level with the cause and the
    /// disposition — and, for a Freezing predecessor, the required
    /// routers whose acks never arrived: a freeze wedge is almost always
    /// one specific non-acking router, and naming it turns the diagnosis
    /// into reading a label. Attribution is best-effort; a failed ack
    /// read must not block the replacement.
    /// Describe a cancellation and log the intent, returning what to
    /// count once it has actually happened.
    async fn describe_cancellation(
        store: &PersonhogStore,
        routers: &[RegisteredRouter],
        predecessor: &HandoffState,
        registered: &HashSet<&str>,
        disposition: &'static str,
    ) -> Cancellation {
        let reason = if registered.contains(predecessor.new_owner.as_str()) {
            "phase_deadline"
        } else {
            "dead_new_owner"
        };
        // Attribution only. A read that fails here must not be turned
        // into an answer: `None` means "no membership recorded", which
        // widens the requirement to every live router, so a transient
        // error would name every one of them as a blocker — during the
        // mass cancellation when etcd is least well and the accusation
        // is least true.
        let missing_ackers = if predecessor.phase == HandoffPhase::Freezing {
            match (
                store.resolve_freeze_quorum(predecessor).await,
                store.list_freeze_acks(predecessor.partition).await,
            ) {
                (Ok(quorum), Ok(acks)) => {
                    missing_freeze_ackers(routers, &acks, predecessor, quorum.as_deref())
                }
                (Err(e), _) | (_, Err(e)) => {
                    tracing::warn!(error = %e, "could not attribute the missing freeze acks");
                    Vec::new()
                }
            }
        } else {
            Vec::new()
        };
        tracing::error!(
            partition = predecessor.partition,
            phase = ?predecessor.phase,
            new_owner = %predecessor.new_owner,
            old_owner = ?predecessor.old_owner,
            reason,
            disposition,
            missing_freeze_ackers = ?missing_ackers,
            "cancelling handoff by replacement"
        );
        Cancellation {
            reason,
            missing_ackers,
        }
    }

    async fn handle_handoff_update_static(
        store: &PersonhogStore,
        handoff: &HandoffState,
    ) -> Result<()> {
        if handoff.phase == HandoffPhase::Complete {
            // Same guarded-delete discipline as the dead-new-owner cancellation:
            // the Complete observation may be stale by the time we act on
            // it, and the record at this key may already be a successor
            // handoff.
            let Some((current, mod_revision)) = store
                .get_handoff_with_mod_revision(handoff.partition)
                .await?
            else {
                return Ok(());
            };
            if current.phase != HandoffPhase::Complete {
                return Ok(());
            }
            tracing::info!(
                partition = current.partition,
                "handoff complete, cleaning up"
            );
            if !store
                .delete_handoff_and_acks_if_unchanged(current.partition, mod_revision)
                .await?
            {
                tracing::info!(
                    partition = current.partition,
                    "handoff changed concurrently, skipping cleanup"
                );
            }
        }
        Ok(())
    }
}

// ── Metrics ─────────────────────────────────────────────────────

fn phase_label(phase: HandoffPhase) -> &'static str {
    match phase {
        HandoffPhase::Freezing => "freezing",
        HandoffPhase::Draining => "draining",
        HandoffPhase::Warming => "warming",
        HandoffPhase::Complete => "complete",
    }
}

/// Record a successful phase advance: a transition counter plus a
/// histogram of milliseconds elapsed since the handoff was created.
/// `started_at` carries one-second resolution, so these timings exist to
/// spot stalls (a handoff minutes into Freezing), not to micro-profile;
/// the pod side's warm and drain histograms carry the precise
/// per-operation cost.
fn record_phase_advance(handoff: &HandoffState, to: HandoffPhase) {
    // Moves drain and warm; fresh assignments only warm — two different
    // duration distributions, split rather than muddled.
    let kind = if handoff.old_owner.is_some() {
        "move"
    } else {
        "fresh"
    };
    counter!(
        "personhog_coordination_handoff_transitions_total",
        "from" => phase_label(handoff.phase),
        "to" => phase_label(to),
    )
    .increment(1);
    let now_ms = util::now_millis();
    // Cumulative creation→phase, millisecond-precise when the record
    // carries `created_at_ms`; pre-upgrade records fall back to the
    // second-resolution `started_at`.
    // Clamped at zero: a phase stamped by one coordinator can be
    // observed by its successor, and millisecond resolution makes even
    // small clock skew visible — a negative observation would distort
    // the histogram, incrementing every bucket.
    let reached_ms = if handoff.created_at_ms > 0 {
        Some(now_ms.saturating_sub(handoff.created_at_ms).max(0))
    } else if handoff.started_at > 0 {
        Some(util::now_seconds().saturating_sub(handoff.started_at) * 1000)
    } else {
        None
    };
    if let Some(reached_ms) = reached_ms {
        histogram!(
            "personhog_coordination_handoff_phase_reached_ms",
            "phase" => phase_label(to),
            "kind" => kind,
        )
        .record(reached_ms as f64);
    }
    // Time spent in the phase being exited. Phases are sequential and
    // non-overlapping, so these are additive components of the total —
    // the handoff waterfall. Zero means a pre-upgrade record with no
    // phase clock; recording an epoch-sized value would be worse than
    // recording nothing.
    if handoff.phase_entered_at_ms > 0 {
        histogram!(
            "personhog_coordination_handoff_phase_duration_ms",
            "phase" => phase_label(handoff.phase),
            "kind" => kind,
        )
        .record(now_ms.saturating_sub(handoff.phase_entered_at_ms).max(0) as f64);
    }
}

/// Refresh the coordinator's view-of-the-cluster gauges. Driven from the
/// reconcile tick, so only the elected coordinator exports live values;
/// `reset_coordinator_gauges` zeroes them when leadership ends.
fn record_cluster_gauges(handoffs: &[HandoffState], pods: &[RegisteredPod], routers: usize) {
    let now_ms = util::now_millis();
    let now_s = util::now_seconds();
    for phase in [
        HandoffPhase::Freezing,
        HandoffPhase::Draining,
        HandoffPhase::Warming,
        HandoffPhase::Complete,
    ] {
        // Oldest time-in-current-phase: the stuck-handoff signal,
        // phase-localized. `phase_reached`/`phase_duration` sample only
        // handoffs that advance, so a wedged one is invisible there —
        // this gauge is its complement, and the one to alert on (age
        // approaching the cancellation deadline means a participant is
        // not acking). Falls back to total age for pre-upgrade records;
        // zero when the phase is empty, which also resets it when
        // leadership ends.
        let max_age_secs = handoffs
            .iter()
            .filter(|h| h.phase == phase)
            .map(|h| {
                if h.phase_entered_at_ms > 0 {
                    now_ms.saturating_sub(h.phase_entered_at_ms) / 1000
                } else if h.started_at > 0 {
                    now_s.saturating_sub(h.started_at)
                } else {
                    0
                }
            })
            .max()
            .unwrap_or(0)
            .max(0);
        gauge!(
            "personhog_coordination_handoff_phase_age_seconds",
            "phase" => phase_label(phase),
        )
        .set(max_age_secs as f64);
        let count = handoffs.iter().filter(|h| h.phase == phase).count();
        gauge!("personhog_coordination_handoffs_in_flight", "phase" => phase_label(phase))
            .set(count as f64);
    }
    for (status, label) in [
        (PodStatus::Ready, "ready"),
        (PodStatus::Draining, "draining"),
    ] {
        let count = pods.iter().filter(|p| p.status == status).count();
        gauge!("personhog_coordination_pods_registered", "status" => label).set(count as f64);
    }
    gauge!("personhog_coordination_routers_registered").set(routers as f64);
}

/// Zero every gauge this instance exports as coordinator. Called when
/// leadership ends, so a former coordinator's scrape endpoint doesn't
/// keep reporting the last-known cluster state alongside the new
/// coordinator's live values.
fn reset_coordinator_gauges() {
    gauge!("personhog_coordination_is_coordinator").set(0.0);
    gauge!("personhog_coordination_generation_hold_pods").set(0.0);
    gauge!("personhog_coordination_generation_capped_pods").set(0.0);
    record_cluster_gauges(&[], &[], 0);
}

// ── Pure functions ──────────────────────────────────────────────

/// Extract sorted pod names from registered pods, filtering to active statuses.
fn active_pod_names(pods: &[RegisteredPod]) -> Vec<String> {
    let mut active: Vec<&RegisteredPod> = pods
        .iter()
        .filter(|p| p.status == PodStatus::Ready)
        .collect();
    active.sort_by(|a, b| a.pod_name.cmp(&b.pod_name));
    active.iter().map(|p| p.pod_name.clone()).collect()
}

/// How long a first evaluation waits for a just-started controller
/// watch's initial intent (a healthy watch reports well under a second).
const FIRST_INTENT_WAIT: Duration = Duration::from_secs(3);

/// Derive assignment members and placement policies from pod
/// registrations and K8s controller intent.
///
/// Outside a rollout every Ready pod is an uncapped active member.
/// Two adjustments during rollouts:
///
/// 1. **Deployment rollout** — old-gen Ready pods become Hold members:
///    they stay serving and keep their assignments, but shed toward the
///    incoming generation, whose Ready pods are capped at their final
///    share (`total_partitions / desired_replicas`) so the first new pod
///    up is never handed the whole partition space. Partitions actually
///    move when an old pod drains (drops out of the member list) or when
///    a below-cap new pod pre-drains a Hold member.
///
/// 2. **StatefulSet rollout** — Draining pods are *kept* as members so
///    their assignments are held. In a StatefulSet rollout the same pod
///    name comes back with a new revision, so there's no point handing
///    off to a different pod.
async fn members_for_k8s(
    k8s: &K8sAwareness,
    pods: &[RegisteredPod],
    total_partitions: u32,
) -> Vec<Member> {
    let mut intents: HashMap<ControllerRef, ClusterIntent> = HashMap::new();
    for pod in pods {
        let Some(controller) = pod.controller.as_ref() else {
            continue;
        };
        if pod.generation.is_empty() || intents.contains_key(controller) {
            continue;
        }
        // Lazily start the controller watch from the registration's own
        // ref — the coordinator has no pod of its own to discover from,
        // and without a watch `classify_departure` has no intent to
        // consult. Idempotent, so calling per evaluation is cheap.
        let newly_watched = match k8s.watch_controller(controller).await {
            Ok(newly_watched) => newly_watched,
            Err(e) => {
                tracing::warn!(
                    controller = %controller,
                    error = %e,
                    "failed to start controller watch; using status-only policy"
                );
                continue;
            }
        };
        // A just-started watch reports no intent yet, and a freshly
        // elected coordinator would otherwise deterministically plan its
        // first evaluation policy-free — mid-rollout, that's a balanced
        // plan moving partitions the rollout already placed. Bound-wait
        // for the first report; on timeout (API server down) fall back
        // to status-only membership, availability over placement.
        let intent = if newly_watched {
            k8s.cluster_intent_within(controller, FIRST_INTENT_WAIT)
                .await
        } else {
            k8s.cluster_intent(controller).await
        };
        if let Some(intent) = intent {
            intents.insert(controller.clone(), intent);
        }
    }

    let members = derive_members(pods, &intents, total_partitions);
    let mut holds = 0u64;
    let mut capped = 0u64;
    for member in &members {
        match member.policy {
            PlacementPolicy::Hold => {
                holds += 1;
                tracing::debug!(
                    pod = %member.name,
                    "holding old-gen deployment pod during generation transition"
                );
            }
            PlacementPolicy::Active { cap: Some(cap) } => {
                capped += 1;
                tracing::debug!(
                    pod = %member.name,
                    cap,
                    "capping new-gen pod at its rollout quota"
                );
            }
            PlacementPolicy::Active { cap: None } => {}
        }
    }
    gauge!("personhog_coordination_generation_hold_pods").set(holds as f64);
    gauge!("personhog_coordination_generation_capped_pods").set(capped as f64);
    members
}

/// Derive placement policies from pod registrations and controller
/// intents. Pure so the policy rules are unit-testable.
///
/// The cap is keyed on departing-generation *siblings*, not on the
/// controller's rollout flag: a Deployment reports the rollout complete
/// the moment its last new-gen pod is up, while the old-gen pods are
/// still registered, still serving, and about to be SIGTERMed. The
/// transition is live — and new-gen pods must keep pulling, capped at
/// their final share — for exactly as long as any departing-generation
/// pod of the same controller remains registered. Otherwise partitions
/// sit on the old generation until termination forces every transfer
/// into the pods' termination grace window.
fn derive_members(
    pods: &[RegisteredPod],
    intents: &HashMap<ControllerRef, ClusterIntent>,
    total_partitions: u32,
) -> Vec<Member> {
    let transitioning: HashSet<&ControllerRef> = pods
        .iter()
        .filter_map(|pod| {
            let (controller, intent) = pod_intent(pod, intents)?;
            (controller.kind == ControllerKind::Deployment
                && classify_departure(intent, &pod.generation) == DepartureReason::Rollout)
                .then_some(controller)
        })
        .collect();

    let mut members: Vec<Member> = Vec::new();
    for pod in pods {
        let policy = match pod_intent(pod, intents) {
            None => base_policy(pod.status),
            Some((controller, intent)) => {
                let reason = classify_departure(intent, &pod.generation);
                match (&controller.kind, pod.status, reason) {
                    // Old-gen Ready pod keeps serving and keeps its
                    // assignments, but receives nothing new and sheds
                    // toward the incoming generation.
                    (ControllerKind::Deployment, PodStatus::Ready, DepartureReason::Rollout) => {
                        Some(PlacementPolicy::Hold)
                    }
                    // Incoming-generation Ready pod is capped at its
                    // final share while the transition is live, computed
                    // fresh each evaluation so an HPA change mid-rollout
                    // adjusts the quota.
                    (ControllerKind::Deployment, PodStatus::Ready, _)
                        if transitioning.contains(controller) && intent.desired_replicas > 0 =>
                    {
                        Some(PlacementPolicy::Active {
                            cap: Some(total_partitions.div_ceil(intent.desired_replicas)),
                        })
                    }
                    // StatefulSet rollout: Draining pod stays a member
                    // (hold assignment) — the same pod name comes back
                    // with a new revision.
                    (
                        ControllerKind::StatefulSet,
                        PodStatus::Draining,
                        DepartureReason::Rollout,
                    ) => Some(PlacementPolicy::Active { cap: None }),
                    _ => base_policy(pod.status),
                }
            }
        };
        if let Some(policy) = policy {
            members.push(Member {
                name: pod.pod_name.clone(),
                policy,
            });
        }
    }
    members.sort_by(|a, b| a.name.cmp(&b.name));
    members
}

/// A pod's controller ref and watched intent, when both are usable.
fn pod_intent<'p, 'i>(
    pod: &'p RegisteredPod,
    intents: &'i HashMap<ControllerRef, ClusterIntent>,
) -> Option<(&'p ControllerRef, &'i ClusterIntent)> {
    let controller = pod.controller.as_ref()?;
    if pod.generation.is_empty() {
        return None;
    }
    let intent = intents.get(controller)?;
    Some((controller, intent))
}

/// Membership when there is no K8s signal: Ready pods are uncapped
/// active members, Draining pods are not members at all.
fn base_policy(status: PodStatus) -> Option<PlacementPolicy> {
    match status {
        PodStatus::Ready => Some(PlacementPolicy::Active { cap: None }),
        PodStatus::Draining => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paced_config(name: &str) -> CoordinatorConfig {
        CoordinatorConfig {
            name: name.to_string(),
            leader_lease_ttl: 5,
            run_retry_backoff: Duration::from_millis(500),
            backoff_decay_window: Duration::from_secs(300),
            ..CoordinatorConfig::default()
        }
    }

    /// The pace must never delay a campaign longer than the lease TTL it
    /// sits inside. A term that ended released the election, so this wait
    /// holds up a succession that is already open — past the TTL a paced
    /// candidate is slower to take a free election than it would have
    /// been to wait out a crashed leader's lease.
    #[test]
    fn the_pace_never_exceeds_the_lease_ttl_it_delays() {
        let config = paced_config("coordinator-0");
        let mut consecutive = 0;
        let mut last = None;
        let ttl = Duration::from_secs(config.leader_lease_ttl as u64);

        for ending in 1..=20 {
            let wait = pace_after_ending(&config, &mut consecutive, &mut last);
            assert!(
                wait <= ttl,
                "ending {ending} paced {wait:?}, past the {ttl:?} lease TTL"
            );
        }
    }

    /// It still has to grow, or it is not a pace at all: a coordinator
    /// that keeps failing would campaign as fast as it can against an
    /// etcd that is already unwell.
    #[test]
    fn the_pace_grows_while_endings_keep_arriving() {
        let config = paced_config("coordinator-0");
        let mut consecutive = 0;
        let mut last = None;

        let first = pace_after_ending(&config, &mut consecutive, &mut last);
        let second = pace_after_ending(&config, &mut consecutive, &mut last);
        assert!(
            second > first,
            "a second ending inside the decay window must pace harder than the first"
        );
    }

    /// And it has to start over once the endings stop, or a bad spell in
    /// the morning leaves every candidate at the cap that evening.
    #[test]
    fn a_quiet_window_starts_the_pace_over() {
        // A window the test can actually wait out, rather than rewinding
        // `last` by subtracting from `Instant::now()` — that subtraction
        // panics on a host whose monotonic clock is younger than the
        // window, which a fresh CI VM's is.
        let config = CoordinatorConfig {
            backoff_decay_window: Duration::from_millis(5),
            ..paced_config("coordinator-0")
        };
        let mut consecutive = 0;
        let mut last = None;

        let first = pace_after_ending(&config, &mut consecutive, &mut last);
        pace_after_ending(&config, &mut consecutive, &mut last);
        // An ending older than the decay window is the same evidence as
        // never having had one.
        std::thread::sleep(config.backoff_decay_window);
        let after_quiet = pace_after_ending(&config, &mut consecutive, &mut last);

        assert_eq!(
            after_quiet, first,
            "an ending after a quiet window must cost the base pace again"
        );
    }

    /// Candidates fail together — one etcd slowdown ends every term at
    /// once — so an unjittered pace walks the whole fleet up the same
    /// ladder and fires their campaigns in the same instant, against an
    /// etcd that has just recovered.
    #[test]
    fn candidates_pace_differently_from_one_another() {
        let waits: HashSet<Duration> = ["router-0", "router-1", "router-2", "router-3"]
            .iter()
            .map(|name| {
                let config = paced_config(name);
                let (mut consecutive, mut last) = (0, None);
                // Third ending: far enough up the ladder that the offset
                // is a meaningful share of the wait.
                for _ in 0..3 {
                    pace_after_ending(&config, &mut consecutive, &mut last);
                }
                pace_after_ending(&config, &mut consecutive, &mut last)
            })
            .collect();

        assert_eq!(
            waits.len(),
            4,
            "every candidate at the same ladder position must wait a distinct time; \
             two of four differing would still let most of the fleet campaign in lockstep"
        );
    }

    fn make_pod(name: &str) -> RegisteredPod {
        RegisteredPod {
            pod_name: name.to_string(),
            generation: String::new(),
            status: PodStatus::Ready,
            registered_at: 0,
            last_heartbeat: 0,
            controller: None,
            advertise_address: None,
        }
    }

    #[test]
    fn active_pod_names_filters_and_sorts() {
        let mut draining = make_pod("pod-0");
        draining.status = PodStatus::Draining;
        let pods = vec![make_pod("pod-2"), draining, make_pod("pod-1")];
        let names = active_pod_names(&pods);
        assert_eq!(names, vec!["pod-1", "pod-2"]);
    }

    fn rollout_intent(
        desired: u32,
        rollout: bool,
        current: &str,
        target: Option<&str>,
    ) -> ClusterIntent {
        ClusterIntent {
            desired_replicas: desired,
            previous_replicas: None,
            rollout_in_progress: rollout,
            current_generation: current.to_string(),
            target_generation: target.map(String::from),
        }
    }

    fn deploy_ref() -> ControllerRef {
        ControllerRef {
            kind: ControllerKind::Deployment,
            name: "deploy".to_string(),
        }
    }

    fn ss_ref() -> ControllerRef {
        ControllerRef {
            kind: ControllerKind::StatefulSet,
            name: "ss".to_string(),
        }
    }

    fn k8s_pod(
        name: &str,
        generation: &str,
        status: PodStatus,
        controller: ControllerRef,
    ) -> RegisteredPod {
        RegisteredPod {
            pod_name: name.to_string(),
            generation: generation.to_string(),
            status,
            registered_at: 0,
            last_heartbeat: 0,
            controller: Some(controller),
            advertise_address: None,
        }
    }

    fn policy_of(members: &[Member], name: &str) -> Option<PlacementPolicy> {
        members.iter().find(|m| m.name == name).map(|m| m.policy)
    }

    #[test]
    fn deployment_rollout_holds_old_gen_and_caps_new_gen() {
        let intents = HashMap::from([(deploy_ref(), rollout_intent(3, true, "old", Some("new")))]);
        let pods = vec![
            k8s_pod("old-0", "old", PodStatus::Ready, deploy_ref()),
            k8s_pod("new-0", "new", PodStatus::Ready, deploy_ref()),
        ];
        let members = derive_members(&pods, &intents, 12);
        assert_eq!(policy_of(&members, "old-0"), Some(PlacementPolicy::Hold));
        assert_eq!(
            policy_of(&members, "new-0"),
            Some(PlacementPolicy::Active { cap: Some(4) })
        );
    }

    /// The regression the k3s rollout test caught: after k8s reports the
    /// rollout complete, still-registered old-gen pods must keep the
    /// caps alive or the placement freezes with everything on the old
    /// generation until termination.
    #[test]
    fn caps_survive_rollout_completion_while_old_gen_registered() {
        let intents = HashMap::from([(deploy_ref(), rollout_intent(2, false, "new", None))]);
        let pods = vec![
            k8s_pod("old-0", "old", PodStatus::Ready, deploy_ref()),
            k8s_pod("old-1", "old", PodStatus::Ready, deploy_ref()),
            k8s_pod("new-0", "new", PodStatus::Ready, deploy_ref()),
            k8s_pod("new-1", "new", PodStatus::Ready, deploy_ref()),
        ];
        let members = derive_members(&pods, &intents, 8);
        assert_eq!(policy_of(&members, "old-0"), Some(PlacementPolicy::Hold));
        assert_eq!(policy_of(&members, "old-1"), Some(PlacementPolicy::Hold));
        assert_eq!(
            policy_of(&members, "new-0"),
            Some(PlacementPolicy::Active { cap: Some(4) })
        );
        assert_eq!(
            policy_of(&members, "new-1"),
            Some(PlacementPolicy::Active { cap: Some(4) })
        );
    }

    /// A draining old-gen pod is not a member but still marks the
    /// transition as live, so its incoming replacements stay capped.
    #[test]
    fn draining_old_gen_pod_keeps_the_transition_live() {
        let intents = HashMap::from([(deploy_ref(), rollout_intent(2, false, "new", None))]);
        let pods = vec![
            k8s_pod("old-0", "old", PodStatus::Draining, deploy_ref()),
            k8s_pod("new-0", "new", PodStatus::Ready, deploy_ref()),
        ];
        let members = derive_members(&pods, &intents, 8);
        assert_eq!(policy_of(&members, "old-0"), None);
        assert_eq!(
            policy_of(&members, "new-0"),
            Some(PlacementPolicy::Active { cap: Some(4) })
        );
    }

    #[test]
    fn deployment_steady_state_is_uncapped() {
        let intents = HashMap::from([(deploy_ref(), rollout_intent(2, false, "gen", None))]);
        let pods = vec![
            k8s_pod("pod-0", "gen", PodStatus::Ready, deploy_ref()),
            k8s_pod("pod-1", "gen", PodStatus::Ready, deploy_ref()),
        ];
        let members = derive_members(&pods, &intents, 8);
        assert_eq!(
            policy_of(&members, "pod-0"),
            Some(PlacementPolicy::Active { cap: None })
        );
        assert_eq!(
            policy_of(&members, "pod-1"),
            Some(PlacementPolicy::Active { cap: None })
        );
    }

    #[test]
    fn zero_desired_replicas_leaves_new_gen_uncapped() {
        let intents = HashMap::from([(deploy_ref(), rollout_intent(0, true, "old", Some("new")))]);
        let pods = vec![
            k8s_pod("old-0", "old", PodStatus::Ready, deploy_ref()),
            k8s_pod("new-0", "new", PodStatus::Ready, deploy_ref()),
        ];
        let members = derive_members(&pods, &intents, 12);
        assert_eq!(
            policy_of(&members, "new-0"),
            Some(PlacementPolicy::Active { cap: None })
        );
    }

    #[test]
    fn missing_intent_falls_back_to_status_only_membership() {
        let intents = HashMap::new();
        let pods = vec![
            k8s_pod("pod-0", "old", PodStatus::Ready, deploy_ref()),
            k8s_pod("pod-1", "old", PodStatus::Draining, deploy_ref()),
        ];
        let members = derive_members(&pods, &intents, 8);
        assert_eq!(
            policy_of(&members, "pod-0"),
            Some(PlacementPolicy::Active { cap: None })
        );
        assert_eq!(policy_of(&members, "pod-1"), None);
    }

    #[test]
    fn statefulset_draining_held_only_during_rollout() {
        let rollout = HashMap::from([(ss_ref(), rollout_intent(3, true, "old", Some("new")))]);
        let pods = vec![k8s_pod("ss-0", "old", PodStatus::Draining, ss_ref())];
        let members = derive_members(&pods, &rollout, 8);
        assert_eq!(
            policy_of(&members, "ss-0"),
            Some(PlacementPolicy::Active { cap: None })
        );

        let steady = HashMap::from([(ss_ref(), rollout_intent(3, false, "gen", None))]);
        let pods = vec![k8s_pod("ss-0", "gen", PodStatus::Draining, ss_ref())];
        let members = derive_members(&pods, &steady, 8);
        assert_eq!(policy_of(&members, "ss-0"), None);
    }

    /// Old-gen pods of one controller must not cap pods of another.
    #[test]
    fn transition_is_scoped_per_controller() {
        let other = ControllerRef {
            kind: ControllerKind::Deployment,
            name: "other".to_string(),
        };
        let intents = HashMap::from([
            (deploy_ref(), rollout_intent(2, false, "new", None)),
            (other.clone(), rollout_intent(2, false, "gen", None)),
        ]);
        let pods = vec![
            k8s_pod("old-0", "old", PodStatus::Ready, deploy_ref()),
            k8s_pod("new-0", "new", PodStatus::Ready, deploy_ref()),
            k8s_pod("other-0", "gen", PodStatus::Ready, other),
        ];
        let members = derive_members(&pods, &intents, 8);
        assert_eq!(
            policy_of(&members, "new-0"),
            Some(PlacementPolicy::Active { cap: Some(4) })
        );
        assert_eq!(
            policy_of(&members, "other-0"),
            Some(PlacementPolicy::Active { cap: None })
        );
    }
}
