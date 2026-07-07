use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use etcd_client::{EventType, WatchStream};
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::parse_watch_value;
use assignment_coordination::util::compute_required_handoffs;
use k8s_awareness::types::ControllerKind;
use k8s_awareness::{DepartureReason, K8sAwareness};

use crate::error::{Error, Result};
use crate::store::{self, PersonhogStore};
use crate::strategy::AssignmentStrategy;
use crate::types::{
    AssignmentStatus, HandoffPhase, HandoffState, PartitionAssignment, PodStatus, RegisteredPod,
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
    /// events. Phase advancement is normally event-driven, but some state
    /// changes produce no watched event at all — a router departing
    /// (nothing watches router registrations) can newly satisfy a freeze
    /// quorum. The tick backstops those so handoffs cannot stall
    /// indefinitely, and doubles as defense-in-depth for anything else
    /// that slips through the event-driven paths.
    pub reconcile_interval: Duration,
}

impl Default for CoordinatorConfig {
    fn default() -> Self {
        Self {
            name: "coordinator-0".to_string(),
            leader_lease_ttl: 15,
            keepalive_interval: Duration::from_secs(5),
            election_retry_interval: Duration::from_secs(5),
            rebalance_debounce_interval: Duration::from_secs(1),
            reconcile_interval: Duration::from_secs(5),
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
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                result = self.try_lead(cancel.clone()) => {
                    match result {
                        Ok(()) => tracing::info!(name = %self.config.name, "leadership ended normally"),
                        Err(e) => tracing::warn!(name = %self.config.name, error = %e, "leader loop ended with error"),
                    }
                    tokio::select! {
                        _ = cancel.cancelled() => return Ok(()),
                        _ = tokio::time::sleep(self.config.election_retry_interval) => {}
                    }
                }
            }
        }
    }

    async fn try_lead(&self, cancel: CancellationToken) -> Result<()> {
        let lease_id = self.store.grant_lease(self.config.leader_lease_ttl).await?;

        let acquired = self
            .store
            .try_acquire_leadership(&self.config.name, lease_id)
            .await?;

        if !acquired {
            tracing::debug!(name = %self.config.name, "another coordinator is leader, standing by");
            return Ok(());
        }

        tracing::info!(name = %self.config.name, "acquired leadership");

        // Spawn lease keepalive
        let keepalive_cancel = cancel.child_token();
        let keepalive_handle = {
            let store = Arc::clone(&self.store);
            let interval = self.config.keepalive_interval;
            let token = keepalive_cancel.clone();
            tokio::spawn(async move {
                if let Err(e) = util::run_lease_keepalive(store, lease_id, interval, token).await {
                    tracing::error!(error = %e, "keepalive failed");
                }
            })
        };

        let result = self.run_coordination_loop(cancel.clone()).await;

        // Clean up keepalive
        keepalive_cancel.cancel();
        drop(keepalive_handle.await);

        // Best-effort revoke so next leader can take over quickly
        drop(self.store.revoke_lease(lease_id).await);

        result
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

        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let k8s_awareness = self.k8s_awareness.clone();
            let debounce_interval = self.config.rebalance_debounce_interval;
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_pods_loop(
                    store,
                    strategy,
                    k8s_awareness,
                    debounce_interval,
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
            let token = cancel.child_token();
            tasks.spawn(async move { Self::reconcile_tick_loop(store, interval, token).await });
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
        cancel: CancellationToken,
        mut stream: WatchStream,
    ) -> Result<()> {
        loop {
            // Wait for the first pod event
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
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
                    // handoffs have completed. If so, re-trigger rebalancing to
                    // pick up any pod changes that were deferred.
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
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut tick = tokio::time::interval(interval);
        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tick.tick() => {
                    for handoff in store.list_handoffs().await? {
                        Self::handle_handoff_update_static(&store, &handoff).await?;
                        Self::check_phase_advance(&store, handoff.partition).await?;
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

                // Identity-based quorum: every currently registered router
                // must have acked this partition's freeze. A count
                // comparison would let a stale ack from a departed router
                // (acks are not lease-bound) stand in for a live router
                // that hasn't stashed yet — advancing to Draining while
                // that router still forwards writes to the old owner.
                //
                // With zero routers there is no traffic to stash, so the
                // freeze quorum is vacuously met. This keeps bootstrap and
                // router-less configurations (e.g. tests exercising only
                // the coordinator+pod) unblocked.
                let acked: HashSet<&str> =
                    freeze_acks.iter().map(|a| a.router_name.as_str()).collect();
                let all_routers_frozen = routers
                    .iter()
                    .all(|r| acked.contains(r.router_name.as_str()));

                if all_routers_frozen {
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
                let old_owner_condition = match &handoff.old_owner {
                    // Defensive: a handoff that reached Draining without
                    // an old owner shouldn't exist (Freezing skips
                    // Draining when old_owner is None), but if it does,
                    // there's nothing to drain.
                    None => true,
                    Some(name) => {
                        // "Alive" here means the pod's etcd registration key
                        // still exists (its lease hasn't expired) — not just
                        // that it's `Ready`. A `Draining` pod is shutting
                        // down gracefully but is still capable of running its
                        // handoff handler and writing a `DrainedAck`, and may
                        // still have inflight handlers. Bypassing the drain
                        // requirement for such a pod would let the
                        // coordinator advance to Warming while the old owner
                        // is still producing — breaking the protocol's core
                        // invariant. Only treat the old owner as drained
                        // when its key is genuinely absent.
                        let pods = store.list_pods().await?;
                        let old_owner_present = pods.iter().any(|p| p.pod_name == *name);
                        if !old_owner_present {
                            true
                        } else {
                            let drained_acks = store.list_drained_acks(partition).await?;
                            drained_acks.iter().any(|a| a.pod_name == *name)
                        }
                    }
                };

                if old_owner_condition {
                    let advanced = store
                        .cas_handoff_phase(partition, HandoffPhase::Draining, HandoffPhase::Warming)
                        .await?;
                    if advanced {
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
                let new_owner_warmed = warmed.iter().any(|a| a.pod_name == handoff.new_owner);

                if new_owner_warmed {
                    tracing::info!(
                        partition,
                        new_owner = %handoff.new_owner,
                        "new owner warmed, completing handoff"
                    );
                    match store.complete_handoff(partition).await {
                        Ok(true) => {}
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

        // Skip rebalancing while handoffs are in flight to prevent overlapping
        // rebalances from overwriting each other. The watch_handoffs_loop will
        // re-trigger rebalancing once all handoffs complete.
        let remaining_handoffs = store.list_handoffs().await?;
        if !remaining_handoffs.is_empty() {
            tracing::info!(
                in_flight = remaining_handoffs.len(),
                "handoffs in progress, deferring rebalance"
            );
            return Ok(());
        }

        let current_assignments = store.list_assignments().await?;

        let current_map: HashMap<u32, String> = current_assignments
            .iter()
            .map(|a| (a.partition, a.owner.clone()))
            .collect();

        let new_assignments =
            strategy.compute_assignments(&current_map, &active_pods, total_partitions);
        let reassignments = compute_required_handoffs(&current_map, &new_assignments);

        // Every partition that has a new owner goes through the handoff
        // protocol, including partitions that had no prior owner (initial
        // assignment). This guarantees routers never route to a pod whose
        // cache hasn't been warmed.
        //
        // Partitions that already have the correct owner are skipped.
        let assigned_partitions: HashSet<u32> = new_assignments.keys().copied().collect();
        let reassignment_partitions: HashSet<u32> =
            reassignments.iter().map(|(p, _, _)| *p).collect();

        // Fresh partitions = assigned but neither in current nor being reassigned.
        let fresh_partitions: Vec<u32> = assigned_partitions
            .iter()
            .copied()
            .filter(|p| !current_map.contains_key(p) && !reassignment_partitions.contains(p))
            .collect();

        if reassignments.is_empty() && fresh_partitions.is_empty() {
            tracing::debug!("no handoffs needed");
            return Ok(());
        }

        let now = util::now_seconds();
        let mut handoff_objects: Vec<HandoffState> = Vec::new();

        // Reassignments: old_owner = Some(prior owner)
        for (partition, old_owner, new_owner) in &reassignments {
            handoff_objects.push(HandoffState {
                partition: *partition,
                old_owner: Some(old_owner.clone()),
                new_owner: new_owner.clone(),
                phase: HandoffPhase::Freezing,
                started_at: now,
            });
        }

        // Fresh assignments: old_owner = None (skip drain, skip release)
        for partition in &fresh_partitions {
            let new_owner = &new_assignments[partition];
            handoff_objects.push(HandoffState {
                partition: *partition,
                old_owner: None,
                new_owner: new_owner.clone(),
                phase: HandoffPhase::Freezing,
                started_at: now,
            });
        }

        tracing::info!(
            reassignments = reassignments.len(),
            fresh = fresh_partitions.len(),
            "creating handoffs"
        );

        // Assignments for partitions that are NOT being moved (correct owner
        // already) still need to be written to etcd, but reassignments and
        // fresh assignments defer their PartitionAssignment writes until the
        // handoff reaches Complete.
        let handoff_partitions: HashSet<u32> =
            handoff_objects.iter().map(|h| h.partition).collect();
        let assignment_objects: Vec<PartitionAssignment> = new_assignments
            .iter()
            .map(|(&partition, owner)| PartitionAssignment {
                partition,
                owner: owner.clone(),
                status: AssignmentStatus::Active,
            })
            .collect();
        let stable_assignments: Vec<PartitionAssignment> = assignment_objects
            .into_iter()
            .filter(|a| !handoff_partitions.contains(&a.partition))
            .collect();

        store
            .create_assignments_and_handoffs(&stable_assignments, &handoff_objects)
            .await?;

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
            if !registered_set.contains(handoff.new_owner.as_str()) {
                tracing::warn!(
                    partition = handoff.partition,
                    new_owner = %handoff.new_owner,
                    old_owner = ?handoff.old_owner,
                    phase = ?handoff.phase,
                    "cleaning up handoff targeting a dead new owner"
                );
                store.delete_all_handoff_acks(handoff.partition).await?;
                store.delete_handoff(handoff.partition).await?;
            }
        }

        Ok(())
    }

    async fn handle_handoff_update_static(
        store: &PersonhogStore,
        handoff: &HandoffState,
    ) -> Result<()> {
        if handoff.phase == HandoffPhase::Complete {
            tracing::info!(
                partition = handoff.partition,
                "handoff complete, cleaning up"
            );
            store.delete_all_handoff_acks(handoff.partition).await?;
            store.delete_handoff(handoff.partition).await?;
        }
        Ok(())
    }
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
