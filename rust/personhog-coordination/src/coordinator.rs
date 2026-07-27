use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use etcd_client::{EventType, WatchStream};
use metrics::{counter, gauge, histogram};
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use k8s_awareness::types::ControllerKind;
use k8s_awareness::{DepartureReason, K8sAwareness};

use crate::error::{Error, Result};
use crate::protocol::{drain_satisfied, freeze_quorum_met, plan_partial_rebalance, warm_satisfied};
use crate::store::{self, PersonhogStore};
use crate::strategy::AssignmentStrategy;
use crate::types::{AssignmentPrecondition, HandoffPhase, HandoffState, PodStatus, RegisteredPod};

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
    /// events. Phase advancement is normally event-driven, but some state
    /// changes produce no watched event at all — a router departing
    /// (nothing watches router registrations) can newly satisfy a freeze
    /// quorum. The tick backstops those so handoffs cannot stall
    /// indefinitely, and doubles as defense-in-depth for anything else
    /// that slips through the event-driven paths.
    pub reconcile_interval: Duration,
    /// How long a handoff may sit in a pre-terminal phase before the
    /// coordinator cancels it and lets the next plan try again.
    ///
    /// This is the backstop for causes we have not found: a participant
    /// that never acks leaves a handoff that no other path removes —
    /// cleanup only deletes handoffs whose new owner is gone, and an
    /// in-flight handoff pins its partition so no re-plan can touch it.
    /// Cancelling is the only safe response; force-advancing past a
    /// missing freeze ack is exactly the split-brain the quorum exists
    /// to prevent.
    ///
    /// Measured against the handoff's total age rather than time in its
    /// current phase: `started_at` is the only timestamp the record
    /// carries, and a per-phase budget derived from it would silently
    /// shrink for whichever phase happened to run last. One end-to-end
    /// budget is also the honest statement of intent — a handoff should
    /// finish, and how it divides its time between freezing, draining,
    /// and warming is not something to police.
    ///
    /// Generous by design: healthy handoffs complete in a few seconds,
    /// so this sits orders of magnitude above them. Too tight a bound
    /// would cancel the handoffs that are merely slow.
    ///
    /// Ages are wall-clock differences that may span machines: a
    /// handoff created by one coordinator can be evaluated by its
    /// successor after a failover, so clock skew between nodes shifts
    /// the effective deadline by its magnitude. That is tolerated
    /// rather than engineered away — skew is NTP-bounded at
    /// milliseconds against a deadline of minutes, and a mistimed
    /// cancellation is safe in either direction: early, the re-plan
    /// recreates the handoff stamped and judged by one clock; late, a
    /// wedge lives that much longer before cancellation.
    pub handoff_deadline: Duration,
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
        }
    }
}

pub struct Coordinator {
    store: Arc<PersonhogStore>,
    config: CoordinatorConfig,
    strategy: Arc<dyn AssignmentStrategy>,
    k8s_awareness: Option<Arc<K8sAwareness>>,
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
            let token = keepalive_cancel.clone();
            let lease_lost = lease_lost.clone();
            tokio::spawn(async move {
                if let Err(e) = util::run_lease_keepalive(store, lease_id, interval, token).await {
                    tracing::error!(error = %e, "election lease keepalive failed");
                    lease_lost.cancel();
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
            let replan = Arc::clone(&replan);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_pods_loop(
                    store,
                    strategy,
                    k8s_awareness,
                    debounce_interval,
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
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_handoffs_loop(store, strategy, k8s_awareness, token, handoffs_stream)
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
            let interval = self.config.reconcile_interval;
            let handoff_deadline = self.config.handoff_deadline;
            let replan = Arc::clone(&replan);
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::reconcile_tick_loop(store, interval, handoff_deadline, replan, token).await
            });
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

    async fn watch_pods_loop(
        store: Arc<PersonhogStore>,
        strategy: Arc<dyn AssignmentStrategy>,
        k8s_awareness: Option<Arc<K8sAwareness>>,
        debounce_interval: Duration,
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

            Self::handle_pod_change_static(&store, strategy.as_ref(), k8s_awareness.as_deref())
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
                                    Self::check_phase_advance(&store, handoff.partition).await?;
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
                                let key = std::str::from_utf8(kv.key()).ok()?;
                                store::extract_partition_from_ack_key(key)
                            });

                            if let Some(partition) = partition {
                                Self::check_phase_advance(store, partition).await?;
                            }
                        }
                    }
                }
            }
        }
    }

    /// Periodically re-evaluate every in-flight handoff, mirroring what
    /// the ack watches do on events. This is the liveness backstop for
    /// state changes that fire no watched event — a router departing
    /// (nothing watches router registrations) can newly satisfy a freeze
    /// quorum. All the work it drives is idempotent: phase transitions
    /// use CAS and completed-handoff cleanup tolerates already-deleted
    /// records.
    async fn reconcile_tick_loop(
        store: Arc<PersonhogStore>,
        interval: Duration,
        handoff_deadline: Duration,
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
                        Self::check_phase_advance(&store, handoff.partition).await?;
                    }
                    // Advancement first, cancellation second: a handoff
                    // that can still progress gets every chance to before
                    // its deadline is considered. A cancellation wakes
                    // the planning loop, since deleting a handoff fires
                    // no pod event and the placement is now short of
                    // desired.
                    if Self::cancel_expired_handoffs(&store, &handoffs, handoff_deadline).await? {
                        replan.notify_one();
                    }
                    // The gauge refresh is best-effort and runs after the
                    // reconcile pass: its reads exist only for metrics and
                    // must never delay or interrupt handoff advancement —
                    // this tick is the liveness backstop for router
                    // departures, which fire no watched event. A skipped
                    // refresh is repaired by the next tick.
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
    async fn check_phase_advance(store: &PersonhogStore, partition: u32) -> Result<()> {
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
                        tracing::info!(
                            partition,
                            freeze_acks = freeze_acks.len(),
                            routers = routers.len(),
                            old_owner = ?handoff.old_owner,
                            ?target,
                            "freeze quorum reached, advanced from Freezing"
                        );
                    }
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
            Self::check_phase_advance(&self.store, handoff.partition).await?;
        }

        Ok(())
    }

    /// Handle a pod registration/deletion by recomputing assignments.
    async fn handle_pod_change(&self) -> Result<()> {
        Self::handle_pod_change_static(
            &self.store,
            self.strategy.as_ref(),
            self.k8s_awareness.as_deref(),
        )
        .await
    }

    async fn handle_pod_change_static(
        store: &PersonhogStore,
        strategy: &dyn AssignmentStrategy,
        k8s_awareness: Option<&K8sAwareness>,
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

        // Clean up any in-flight handoffs targeting pods whose etcd
        // registration has disappeared. This happens when a pod crashes
        // during the Warming phase before it can ack — the handoff would
        // be stuck forever otherwise.
        Self::cleanup_stale_handoffs(store).await?;

        // In-flight handoffs pin their partitions: the plan excludes them
        // (no second handoff, no assignment write) and attributes them to
        // their target for the balance math, so a stuck handoff defers
        // only its own partition instead of all rebalancing.
        let in_flight = store.list_handoffs().await?;
        if !in_flight.is_empty() {
            tracing::info!(
                pinned = in_flight.len(),
                "planning around in-flight handoffs"
            );
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
        // model.
        let plan = plan_partial_rebalance(
            strategy,
            &current_map,
            &in_flight,
            &active_pods,
            total_partitions,
        );

        if plan.handoffs.is_empty() {
            tracing::debug!("no handoffs needed");
            return Ok(());
        }

        // Snapshot the routers that must ack these freezes. Read here,
        // once, rather than per-check: the whole point is that the
        // requirement is fixed at creation and cannot grow as routers
        // come and go (see `HandoffState::freeze_quorum`).
        let freeze_quorum: Vec<String> = store
            .list_routers()
            .await?
            .into_iter()
            .map(|r| r.router_name)
            .collect();

        let now = util::now_seconds();
        let now_ms = util::now_millis();
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

        let moves = plan
            .handoffs
            .iter()
            .filter(|h| h.old_owner.is_some())
            .count();
        tracing::info!(
            reassignments = moves,
            fresh = plan.handoffs.len() - moves,
            "creating handoffs"
        );

        // The rebalance writes no assignment records: handoff completion is
        // the sole writer of assignments (see `complete_handoff`'s
        // invariant), so routers always observe owner changes as Complete
        // events, and a stale plan can never restore a superseded owner.
        // Each handoff instead carries a precondition tying it to the
        // snapshot its old_owner came from.
        let preconditions: Vec<AssignmentPrecondition> = handoff_objects
            .iter()
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

        if !store
            .create_assignments_and_handoffs(&[], &handoff_objects, &preconditions)
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

        counter!("personhog_coordination_handoffs_created_total", "kind" => "move")
            .increment(moves as u64);
        counter!("personhog_coordination_handoffs_created_total", "kind" => "fresh")
            .increment((plan.handoffs.len() - moves) as u64);

        // Nudge advancement for handoffs whose preconditions are already
        // satisfied at creation time (no old_owner, dead old_owner, vacuous
        // router quorum). Without this, such handoffs would stall waiting
        // for an ack event that will never arrive — the watch loop's nudge
        // only catches subsequent Put events.
        for handoff in &handoff_objects {
            Self::check_phase_advance(store, handoff.partition).await?;
        }

        Ok(())
    }

    /// Cancel handoffs that have sat in one phase past its deadline.
    ///
    /// Nothing else removes a handoff that simply never gets its ack:
    /// `cleanup_stale_handoffs` only fires when the new owner is gone,
    /// and an in-flight handoff pins its partition so no re-plan can
    /// touch it. Deleting is the only safe response — advancing without
    /// the ack is the split-brain the phase exists to prevent — and the
    /// next plan is free to try again, with a fresh handoff id and a
    /// fresh quorum snapshot.
    ///
    /// Deliberately not backed off: the snapshot rule keeps freeze
    /// quorums satisfiable, so repeated cancellation of one partition
    /// means a new cause, and
    /// `handoffs_cancelled_total{reason="phase_deadline"}` exists to
    /// make that visible rather than absorbed.
    ///
    /// Returns whether anything was cancelled, so the caller can wake
    /// the planning loop — a deletion fires no pod event, and without
    /// the wake no re-plan would run until the next unrelated pod
    /// change. `handoffs` is the caller's already-listed snapshot; each
    /// candidate is re-read under mod_revision before deletion, so the
    /// snapshot's staleness only ever skips a cancel, never misdirects
    /// one.
    async fn cancel_expired_handoffs(
        store: &PersonhogStore,
        handoffs: &[HandoffState],
        handoff_deadline: Duration,
    ) -> Result<bool> {
        let now = util::now_seconds();
        let deadline = handoff_deadline.as_secs() as i64;
        let mut cancelled = false;
        for handoff in handoffs {
            // Complete is terminal and cleaned up by its own path.
            if handoff.phase == HandoffPhase::Complete {
                continue;
            }
            // A record carrying no creation time cannot be judged on age;
            // deleting it would be acting on an age of "since the epoch"
            // rather than on evidence that it is stuck.
            if handoff.started_at <= 0 {
                continue;
            }
            let age = now.saturating_sub(handoff.started_at);
            if age < deadline {
                continue;
            }
            // Re-read under mod_revision and re-verify the phase before
            // deleting: this runs alongside the watch-driven paths, and
            // the record at this key may already be a successor handoff
            // that has not had its own chance yet.
            let Some((current, mod_revision)) = store
                .get_handoff_with_mod_revision(handoff.partition)
                .await?
            else {
                continue;
            };
            if current.handoff_id != handoff.handoff_id
                || current.phase == HandoffPhase::Complete
                || now.saturating_sub(current.started_at) < deadline
            {
                continue;
            }
            tracing::error!(
                partition = current.partition,
                phase = ?current.phase,
                age_secs = age,
                new_owner = %current.new_owner,
                old_owner = ?current.old_owner,
                "handoff exceeded its deadline; cancelling so a later plan can retry"
            );
            if store
                .delete_handoff_and_acks_if_unchanged(current.partition, mod_revision)
                .await?
            {
                cancelled = true;
                counter!(
                    "personhog_coordination_handoffs_cancelled_total",
                    "reason" => "phase_deadline",
                )
                .increment(1);
            }
        }
        Ok(cancelled)
    }

    /// Delete handoffs that cannot progress because the new_owner is gone —
    /// no `WarmedAck` will ever arrive, so the handoff can never complete,
    /// and deleting it lets the next rebalance pick a healthy owner.
    ///
    /// A dead *old* owner is deliberately not grounds for cleanup: Freezing
    /// waits on routers rather than the old owner, and `check_phase_advance`
    /// treats an absent old owner in Draining as vacuously drained, so such
    /// handoffs advance on their own (the reconcile tick guarantees
    /// re-evaluation). Deleting them here would race that advance path and
    /// tear down a healthy in-flight warm on the new owner.
    ///
    /// "Gone" here means the pod's etcd registration is absent — its lease
    /// expired or it deregistered. A `Draining` pod is *not* gone: it is
    /// still alive, still heartbeating, and still capable of running its
    /// handoff handler.
    async fn cleanup_stale_handoffs(store: &PersonhogStore) -> Result<()> {
        let handoffs = store.list_handoffs().await?;
        let pods = store.list_pods().await?;
        let registered_set: HashSet<&str> = pods.iter().map(|p| p.pod_name.as_str()).collect();

        for handoff in &handoffs {
            if registered_set.contains(handoff.new_owner.as_str()) {
                continue;
            }
            // Re-read under mod_revision and re-verify before deleting.
            // This function runs concurrently from the pod watch, the
            // handoff watch, and the reconcile tick (and briefly from an
            // outgoing coordinator during failover): an unguarded delete
            // acting on this loop's snapshot could destroy a successor
            // handoff recreated at the same key, along with its acks.
            let Some((current, mod_revision)) = store
                .get_handoff_with_mod_revision(handoff.partition)
                .await?
            else {
                continue;
            };
            if registered_set.contains(current.new_owner.as_str()) {
                continue;
            }
            tracing::warn!(
                partition = current.partition,
                new_owner = %current.new_owner,
                old_owner = ?current.old_owner,
                phase = ?current.phase,
                "cleaning up handoff targeting a dead new owner"
            );
            if store
                .delete_handoff_and_acks_if_unchanged(current.partition, mod_revision)
                .await?
            {
                counter!("personhog_coordination_handoffs_cancelled_total", "reason" => "dead_new_owner")
                    .increment(1);
            } else {
                tracing::info!(
                    partition = current.partition,
                    "handoff changed concurrently, skipping cleanup"
                );
            }
        }

        Ok(())
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
