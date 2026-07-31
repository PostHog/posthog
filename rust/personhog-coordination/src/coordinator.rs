use std::collections::{HashMap, HashSet};
use std::str::from_utf8;
use std::sync::Arc;
use std::time::{Duration, Instant};

use etcd_client::{EventType, WatchStream};
use metrics::{counter, gauge, histogram};
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use k8s_awareness::types::ControllerKind;
use k8s_awareness::{DepartureReason, K8sAwareness};

use crate::error::{Error, Result};
use crate::protocol::{
    drain_satisfied, freeze_quorum_met, missing_freeze_ackers, past_phase_deadline,
    plan_partial_rebalance, warm_satisfied,
};
use crate::store::{self, PersonhogStore};
use crate::strategy::AssignmentStrategy;
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
    pub election_retry_interval: Duration,
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
            // A crashed leader blocks every handoff until its election
            // lease expires and a survivor's next campaign fires, so the
            // worst-case coordinator outage is ttl + retry. 5s + 1s keeps
            // that near the pod-crash detection window, while the 1s
            // keepalive gives the leader several attempts within the TTL
            // before it abdicates. Graceful exits don't wait on any of
            // this — the lease is revoked on the way out.
            leader_lease_ttl: 5,
            keepalive_interval: Duration::from_secs(1),
            election_retry_interval: Duration::from_secs(1),
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
    pub async fn run(&self, cancel: CancellationToken) -> Result<()> {
        util::preregister_coordinator_metrics();
        loop {
            if cancel.is_cancelled() {
                return Ok(());
            }
            // Awaited to completion, never raced against cancellation:
            // dropping try_lead mid-cleanup would strand the election
            // lease until TTL expiry, stalling every handoff while the
            // next coordinator's campaign waits it out. try_lead observes
            // `cancel` internally and returns promptly on shutdown.
            match self.try_lead(cancel.clone()).await {
                Ok(true) => tracing::info!(name = %self.config.name, "leadership ended normally"),
                Ok(false) => {}
                Err(e) => {
                    tracing::warn!(name = %self.config.name, error = %e, "leader loop ended with error")
                }
            }
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tokio::time::sleep(self.config.election_retry_interval) => {}
            }
        }
    }

    /// One leadership attempt; returns whether this candidate actually
    /// led. Always runs its cleanup — keepalive shutdown and election
    /// lease revoke — before returning, so a graceful exit frees the
    /// election immediately instead of stranding it until TTL expiry.
    /// `run` relies on that by awaiting this call to completion.
    async fn try_lead(&self, cancel: CancellationToken) -> Result<bool> {
        let granted_at = Instant::now();
        let lease_id = self.store.grant_lease(self.config.leader_lease_ttl).await?;

        let acquired = match self
            .store
            .try_acquire_leadership(&self.config.name, lease_id)
            .await
        {
            Ok(acquired) => acquired,
            Err(e) => {
                drop(self.store.revoke_lease(lease_id).await);
                return Err(e);
            }
        };

        if !acquired {
            tracing::debug!(name = %self.config.name, "another coordinator is leader, standing by");
            // Nothing hangs off the lease; revoke it rather than leaking
            // one lease per election retry from every standby candidate.
            drop(self.store.revoke_lease(lease_id).await);
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
            _ = lease_lost.cancelled() => Err(Error::leadership_lost()),
            result = self.run_coordination_loop(cancel.clone()) => result,
        };

        // Clean up keepalive
        keepalive_cancel.cancel();
        drop(keepalive_handle.await);

        // Revoke so the next candidate's campaign wins immediately instead
        // of waiting out the lease TTL.
        drop(self.store.revoke_lease(lease_id).await);

        reset_coordinator_gauges();

        result.map(|()| true)
    }

    async fn run_coordination_loop(&self, cancel: CancellationToken) -> Result<()> {
        // Anchor every watch to a single revision taken BEFORE bootstrap.
        // The coordinator must observe ack writes (PodDrainedAck,
        // PodWarmedAck, RouterFreezeAck) to advance handoffs; anchoring
        // guarantees that any event from this revision on is delivered
        // even if it lands before a watch finishes attaching, so nothing
        // written during (or racing) bootstrap can be missed. Bootstrap
        // reads happen after this point and may double-observe events the
        // watches also deliver — all downstream work is idempotent
        // (CAS-guarded phase transitions, tolerant cleanup).
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
                    let resp = msg?.ok_or_else(|| Error::invalid_state("pod watch stream ended".to_string()))?;
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
                        let resp = msg?.ok_or_else(|| Error::invalid_state("pod watch stream ended".to_string()))?;
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
                    let resp = msg?.ok_or_else(|| Error::invalid_state("handoff watch stream ended".to_string()))?;
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
                    let resp = msg?.ok_or_else(|| Error::invalid_state(format!("{kind} ack watch stream ended")))?;
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

    /// React to router departures. The freeze quorum's required set is
    /// the handoff's creation snapshot intersected with the live
    /// registry, so a router leaving — deregistering at shutdown, or its
    /// lease expiring after a crash — can newly satisfy the quorum of
    /// every in-flight freeze. Nothing else fires an event for that:
    /// without this watch, such handoffs wait for the reconcile tick.
    /// Registrations (Put events) are ignored — a router that joins
    /// after a handoff's creation is never added to its quorum, so a Put
    /// can't change any evaluation.
    async fn run_router_departure_watch(
        mut stream: WatchStream,
        store: &PersonhogStore,
        cancel: CancellationToken,
    ) -> Result<()> {
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| {
                        Error::invalid_state("router watch stream ended".to_string())
                    })?;
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
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tick.tick() => {
                    let handoffs = store.list_handoffs().await?;
                    for handoff in &handoffs {
                        Self::handle_handoff_update_static(&store, handoff).await?;
                        Self::check_phase_advance(&store, handoff.partition, AdvanceTrigger::Other).await?;
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

                // Quorum semantics live in `protocol::freeze_quorum_met`
                // (shared with the stateright model).
                if freeze_quorum_met(&routers, &freeze_acks, &handoff) {
                    // Initial assignments (no old owner) skip Draining
                    // entirely — there's no inflight to wait for. Advance
                    // straight to Warming.
                    let target = match handoff.old_owner {
                        None => HandoffPhase::Warming,
                        Some(_) => HandoffPhase::Draining,
                    };
                    let advanced = store
                        .cas_handoff_phase(partition, HandoffPhase::Freezing, target)
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
                        missing_freeze_ackers =
                            ?missing_freeze_ackers(&routers, &freeze_acks, &handoff),
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
                        .cas_handoff_phase(partition, HandoffPhase::Draining, HandoffPhase::Warming)
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
                    match store.complete_handoff(partition).await {
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

        let mut active_pods = active_pod_names(&pods);

        // K8s-aware pod filtering for smarter rebalancing
        if let Some(k8s) = k8s_awareness {
            active_pods = filter_pods_for_k8s(k8s, &pods, active_pods).await;
        }

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
        let plan = plan_partial_rebalance(
            strategy,
            &current_map,
            &pinned,
            &active_pods,
            total_partitions,
        );

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
                freeze_quorum: Some(freeze_quorum.clone()),
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
        let mut fallback_deletes: Vec<(HandoffState, i64)> = Vec::new();
        let mut replaced_dispositions: Vec<&'static str> = Vec::new();

        for handoff in handoff_objects {
            match cancelled_by_partition.remove(&handoff.partition) {
                Some((predecessor, mod_revision)) => {
                    Self::log_cancellation(store, &routers, &predecessor, &registered, "successor")
                        .await;
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
                    Self::log_cancellation(store, &routers, &predecessor, &registered, "reaffirm")
                        .await;
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
                            freeze_quorum: Some(Vec::new()),
                            created_at_ms: now_ms,
                            phase_entered_at_ms: now_ms,
                        },
                        expected_mod_revision: mod_revision,
                    });
                    replaced_dispositions.push("reaffirm");
                }
                None => {
                    Self::log_cancellation(store, &routers, &predecessor, &registered, "delete")
                        .await;
                    fallback_deletes.push((predecessor, mod_revision));
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

        if (!creations.is_empty() || !replacements.is_empty())
            && !store
                .apply_plan(&[], &creations, &replacements, &preconditions)
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
        for (predecessor, mod_revision) in fallback_deletes {
            if store
                .delete_handoff_and_acks_if_unchanged(predecessor.partition, mod_revision)
                .await?
            {
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
    async fn log_cancellation(
        store: &PersonhogStore,
        routers: &[RegisteredRouter],
        predecessor: &HandoffState,
        registered: &HashSet<&str>,
        disposition: &'static str,
    ) {
        let reason = if registered.contains(predecessor.new_owner.as_str()) {
            "phase_deadline"
        } else {
            "dead_new_owner"
        };
        let missing_ackers = if predecessor.phase == HandoffPhase::Freezing {
            match store.list_freeze_acks(predecessor.partition).await {
                Ok(acks) => missing_freeze_ackers(routers, &acks, predecessor),
                Err(e) => {
                    tracing::warn!(error = %e, "could not read freeze acks for attribution");
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
        counter!(
            "personhog_coordination_handoffs_cancelled_total",
            "reason" => reason,
        )
        .increment(1);
        for router in &missing_ackers {
            counter!(
                "personhog_coordination_freeze_ack_missing_total",
                "router" => router.clone(),
            )
            .increment(1);
        }
    }

    async fn handle_handoff_update_static(
        store: &PersonhogStore,
        handoff: &HandoffState,
    ) -> Result<()> {
        if handoff.phase == HandoffPhase::Complete {
            // Same guarded-delete discipline as `cleanup_stale_handoffs`:
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

/// Adjust the active pod list based on K8s controller intent.
///
/// Two adjustments during rollouts:
///
/// 1. **Deployment rollout** — old-gen Ready pods are excluded from the
///    active list so the strategy never assigns partitions to them. Existing
///    assignments move to new-gen pods via handoff.
///
/// 2. **StatefulSet rollout** — Draining pods are *added back* to the
///    active list so their assignments are held. In a StatefulSet rollout the
///    same pod name comes back with a new revision, so there's no point
///    handing off to a different pod.
async fn filter_pods_for_k8s(
    k8s: &K8sAwareness,
    pods: &[RegisteredPod],
    mut active: Vec<String>,
) -> Vec<String> {
    for pod in pods {
        let (Some(controller), generation) = (&pod.controller, &pod.generation) else {
            continue;
        };

        if generation.is_empty() {
            continue;
        }

        // Lazily start the controller watch from the registration's own
        // ref — the coordinator has no pod of its own to discover from,
        // and without a watch `classify_departure` has no intent to
        // consult. Idempotent, so calling per evaluation is cheap; the
        // first evaluation after a watch starts may still classify
        // Unknown, which safely leaves the pod active until intent
        // arrives.
        if let Err(e) = k8s.watch_controller(controller).await {
            tracing::warn!(
                controller = %controller,
                error = %e,
                "failed to start controller watch; treating pod as active"
            );
            continue;
        }

        let reason = k8s.classify_departure(controller, generation).await;

        match (&controller.kind, pod.status, reason) {
            // Deployment rollout: old-gen Ready pod → exclude
            (ControllerKind::Deployment, PodStatus::Ready, DepartureReason::Rollout) => {
                tracing::info!(
                    pod = %pod.pod_name,
                    controller = %controller,
                    generation = %generation,
                    "excluding old-gen deployment pod from active list"
                );
                active.retain(|name| name != &pod.pod_name);
            }
            // StatefulSet rollout: Draining pod → add back (hold assignment)
            (ControllerKind::StatefulSet, PodStatus::Draining, DepartureReason::Rollout) => {
                tracing::info!(
                    pod = %pod.pod_name,
                    controller = %controller,
                    generation = %generation,
                    "holding assignment for statefulset pod during rollout"
                );
                if !active.contains(&pod.pod_name) {
                    active.push(pod.pod_name.clone());
                }
            }
            _ => {}
        }
    }

    active.sort();
    active.dedup();
    active
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
