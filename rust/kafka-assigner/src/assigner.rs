use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use etcd_client::EventType;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

use assignment_coordination::leader_election::{self, LeaderElectionConfig};
use assignment_coordination::strategy::AssignmentStrategy;
use assignment_coordination::util;

use crate::error::{Error, Result};
use crate::store::{self, KafkaAssignerStore};
use crate::types::{
    AssignmentStatus, ConsumerStatus, HandoffPhase, HandoffState, PartitionAssignment,
    RegisteredConsumer,
};

#[derive(Debug, Clone)]
pub struct AssignerConfig {
    pub name: String,
    pub leader_lease_ttl: i64,
    pub keepalive_interval: Duration,
    pub election_retry_interval: Duration,
    /// How long to wait after the first consumer event before rebalancing,
    /// to batch rapid consumer registrations into a single rebalance.
    pub rebalance_debounce_interval: Duration,
    /// Maximum time a handoff can stay in any phase before being cleaned up.
    pub handoff_timeout: Duration,
}

impl Default for AssignerConfig {
    fn default() -> Self {
        Self {
            name: "assigner-0".to_string(),
            leader_lease_ttl: 15,
            keepalive_interval: Duration::from_secs(5),
            election_retry_interval: Duration::from_secs(5),
            rebalance_debounce_interval: Duration::from_secs(1),
            handoff_timeout: Duration::from_secs(300),
        }
    }
}

impl From<&crate::config::Config> for AssignerConfig {
    fn from(config: &crate::config::Config) -> Self {
        Self {
            name: config.assigner_name.clone(),
            leader_lease_ttl: config.leader_lease_ttl_secs,
            keepalive_interval: config.leader_keepalive_interval(),
            election_retry_interval: config.election_retry_interval(),
            rebalance_debounce_interval: config.rebalance_debounce_interval(),
            handoff_timeout: config.handoff_timeout(),
        }
    }
}

pub struct Assigner {
    store: Arc<KafkaAssignerStore>,
    config: AssignerConfig,
    strategy: Arc<dyn AssignmentStrategy>,
}

impl Assigner {
    pub fn new(
        store: Arc<KafkaAssignerStore>,
        config: AssignerConfig,
        strategy: Arc<dyn AssignmentStrategy>,
    ) -> Self {
        Self {
            store,
            config,
            strategy,
        }
    }

    /// Run the assigner loop. Continuously attempts leader election;
    /// when elected, runs the assignment loop until leadership is lost
    /// or cancellation is requested.
    pub async fn run(&self, cancel: CancellationToken) -> Result<()> {
        let client = self.store.inner().client().clone();
        let leader_key = format!("{}assigner/leader", self.store.inner().prefix());

        let election_config = LeaderElectionConfig {
            name: self.config.name.clone(),
            leader_key,
            lease_ttl: self.config.leader_lease_ttl,
            keepalive_interval: self.config.keepalive_interval,
            retry_interval: self.config.election_retry_interval,
        };

        leader_election::run_as_leader(
            client,
            election_config,
            cancel,
            |leadership_cancel| async {
                self.run_coordination_loop(leadership_cancel)
                    .await
                    .map_err(Into::into)
            },
        )
        .await?;

        Ok(())
    }

    async fn run_coordination_loop(&self, cancel: CancellationToken) -> Result<()> {
        // Compute initial assignments for any consumers already registered
        self.handle_consumer_change(self.config.handoff_timeout)
            .await?;

        // Serialize rebalance execution across all loops to prevent
        // concurrent read-then-write races on assignments and handoffs.
        let rebalance_guard: Arc<Mutex<()>> = Arc::new(Mutex::new(()));

        // Watch consumers and handoffs concurrently
        let mut tasks = tokio::task::JoinSet::new();

        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let guard = Arc::clone(&rebalance_guard);
            let debounce_interval = self.config.rebalance_debounce_interval;
            let handoff_timeout = self.config.handoff_timeout;
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_consumers_loop(
                    store,
                    strategy,
                    guard,
                    debounce_interval,
                    handoff_timeout,
                    token,
                )
                .await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let guard = Arc::clone(&rebalance_guard);
            let handoff_timeout = self.config.handoff_timeout;
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_handoffs_loop(store, strategy, guard, handoff_timeout, token).await
            });
        }

        // Periodic cleanup loop: catches timed-out handoffs that the
        // event-driven watch loops miss (e.g. when the system is quiescent
        // and no consumer/handoff events are firing).
        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let guard = Arc::clone(&rebalance_guard);
            let handoff_timeout = self.config.handoff_timeout;
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::periodic_cleanup_loop(store, strategy, guard, handoff_timeout, token).await
            });
        }

        let result = tokio::select! {
            _ = cancel.cancelled() => Ok(()),
            Some(result) = tasks.join_next() => {
                result.map_err(|e| Error::invalid_state(format!("task panicked: {e}")))?
            }
        };

        tasks.shutdown().await;

        result
    }

    // ── Watch loops ──────────────────────────────────────────────

    async fn watch_consumers_loop(
        store: Arc<KafkaAssignerStore>,
        strategy: Arc<dyn AssignmentStrategy>,
        rebalance_guard: Arc<Mutex<()>>,
        debounce_interval: Duration,
        handoff_timeout: Duration,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_consumers().await?;

        loop {
            // Wait for the first consumer event
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("consumer watch stream ended"))?;
                    Self::log_consumer_events(&resp);
                }
            }

            // Drain additional events arriving within the debounce window
            let deadline = tokio::time::Instant::now() + debounce_interval;
            loop {
                tokio::select! {
                    _ = cancel.cancelled() => return Ok(()),
                    _ = tokio::time::sleep_until(deadline) => break,
                    msg = stream.message() => {
                        let resp = msg?.ok_or_else(|| Error::invalid_state("consumer watch stream ended"))?;
                        Self::log_consumer_events(&resp);
                    }
                }
            }

            let _lock = rebalance_guard.lock().await;
            Self::handle_consumer_change_static(&store, strategy.as_ref(), handoff_timeout).await?;
        }
    }

    fn log_consumer_events(resp: &etcd_client::WatchResponse) {
        for event in resp.events() {
            match event.event_type() {
                EventType::Put => tracing::info!("consumer registered or updated"),
                EventType::Delete => tracing::warn!("consumer lease expired or deleted"),
            }
        }
    }

    async fn watch_handoffs_loop(
        store: Arc<KafkaAssignerStore>,
        strategy: Arc<dyn AssignmentStrategy>,
        rebalance_guard: Arc<Mutex<()>>,
        handoff_timeout: Duration,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_handoffs().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("handoff watch stream ended"))?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            match store::parse_watch_value::<HandoffState>(event) {
                                Ok(handoff) => {
                                    Self::handle_handoff_update(&store, &handoff).await?;
                                }
                                Err(e) => {
                                    tracing::error!(error = %e, "failed to parse handoff event");
                                }
                            }
                        }
                    }

                    let _lock = rebalance_guard.lock().await;

                    // Clean up handoffs that can no longer make progress
                    // (e.g. old_owner died at Complete phase — nobody will
                    // call PartitionReleased to delete the handoff).
                    let consumers = store.list_consumers().await?;
                    let active = active_consumer_names(&consumers);
                    Self::cleanup_stale_handoffs(&store, &active, handoff_timeout).await?;

                    // After processing all events, check if all handoffs have
                    // completed. If so, re-trigger rebalancing to pick up any
                    // consumer changes that were deferred.
                    if store.list_handoffs().await?.is_empty() {
                        Self::handle_consumer_change_static(&store, strategy.as_ref(), handoff_timeout).await?;
                    }
                }
            }
        }
    }

    /// Periodically clean up timed-out handoffs and re-trigger rebalancing.
    ///
    /// The watch-based loops only run cleanup when events arrive. If the
    /// system is quiescent (no consumer changes, no handoff updates), stale
    /// handoffs can block rebalancing indefinitely. This loop runs every
    /// `handoff_timeout / 2` to catch those cases.
    async fn periodic_cleanup_loop(
        store: Arc<KafkaAssignerStore>,
        strategy: Arc<dyn AssignmentStrategy>,
        rebalance_guard: Arc<Mutex<()>>,
        handoff_timeout: Duration,
        cancel: CancellationToken,
    ) -> Result<()> {
        // Check at half the timeout interval so we catch stale handoffs
        // reasonably soon after they expire.
        let interval = handoff_timeout / 2;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tokio::time::sleep(interval) => {
                    let _lock = rebalance_guard.lock().await;

                    let consumers = store.list_consumers().await?;
                    let active = active_consumer_names(&consumers);
                    Self::cleanup_stale_handoffs(&store, &active, handoff_timeout).await?;

                    if store.list_handoffs().await?.is_empty() {
                        Self::handle_consumer_change_static(&store, strategy.as_ref(), handoff_timeout).await?;
                    }
                }
            }
        }
    }

    // ── Handoff handling ─────────────────────────────────────────

    async fn handle_handoff_update(
        store: &KafkaAssignerStore,
        handoff: &HandoffState,
    ) -> Result<()> {
        match handoff.phase {
            // New consumer signaled Ready — complete the handoff directly.
            // No router ack quorum like personhog; the coordinator drives
            // the transition.
            HandoffPhase::Ready => {
                let tp = handoff.topic_partition();
                tracing::info!(
                    topic = %tp.topic,
                    partition = tp.partition,
                    "consumer ready, completing handoff"
                );
                match store.complete_handoff(&tp).await {
                    Ok(true) => {}
                    Ok(false) => {
                        tracing::warn!(
                            topic = %tp.topic,
                            partition = tp.partition,
                            "handoff was modified concurrently, skipping"
                        );
                    }
                    Err(Error::NotFound(_)) => {
                        tracing::warn!(
                            topic = %tp.topic,
                            partition = tp.partition,
                            "handoff already deleted, ignoring"
                        );
                    }
                    Err(e) => return Err(e),
                }
            }
            // Handoff completed — assignment owner updated. The relay will
            // send a Release command to the old consumer, who will call
            // PartitionReleased to delete the handoff key.
            HandoffPhase::Complete => {}
            HandoffPhase::Warming => {}
        }
        Ok(())
    }

    // ── Rebalancing ──────────────────────────────────────────────

    async fn handle_consumer_change(&self, handoff_timeout: Duration) -> Result<()> {
        Self::handle_consumer_change_static(&self.store, self.strategy.as_ref(), handoff_timeout)
            .await
    }

    async fn handle_consumer_change_static(
        store: &KafkaAssignerStore,
        strategy: &dyn AssignmentStrategy,
        handoff_timeout: Duration,
    ) -> Result<()> {
        let consumers = store.list_consumers().await?;
        let ready_consumers = active_consumer_names(&consumers);
        let registered = registered_consumer_names(&consumers);

        // Clean up handoffs targeting consumers that are no longer active.
        Self::cleanup_stale_handoffs(store, &ready_consumers, handoff_timeout).await?;

        // No registered consumers at all: delete all assignments so stale keys don't linger.
        if registered.is_empty() {
            tracing::info!("no registered consumers, clearing all assignments");
            store.delete_all_assignments().await?;
            return Ok(());
        }

        // Skip rebalancing while handoffs are in flight to prevent
        // overlapping rebalances. watch_handoffs_loop re-triggers
        // rebalancing once all handoffs complete.
        let remaining_handoffs = store.list_handoffs().await?;
        if !remaining_handoffs.is_empty() {
            tracing::info!(
                in_flight = remaining_handoffs.len(),
                "handoffs in progress, deferring rebalance"
            );
            return Ok(());
        }

        // No Ready consumers to assign to (but some are still registered/draining).
        if ready_consumers.is_empty() {
            tracing::debug!("no ready consumers, skipping assignment");
            return Ok(());
        }

        let topic_configs = store.list_topic_configs().await?;
        if topic_configs.is_empty() {
            tracing::debug!("no topic configs, skipping assignment");
            return Ok(());
        }

        let mut all_assignments: Vec<PartitionAssignment> = Vec::new();
        let mut all_handoffs: Vec<HandoffState> = Vec::new();
        let mut has_changes = false;
        let now = util::now_seconds();
        // Use registered set for liveness: a Draining consumer is alive and
        // needs the handoff protocol, not a direct reassignment.
        let registered_set: HashSet<&str> = registered.iter().map(|s| s.as_str()).collect();

        for config in &topic_configs {
            let current_assignments = store.list_assignments_for_topic(&config.topic).await?;
            let current_map: HashMap<u32, String> = current_assignments
                .iter()
                .map(|a| (a.partition, a.owner.clone()))
                .collect();

            let desired = strategy.compute_assignments(
                &current_map,
                &ready_consumers,
                config.partition_count,
            );
            let moves = util::compute_required_handoffs(&current_map, &desired);

            if !moves.is_empty() || current_map.len() != desired.len() {
                has_changes = true;
            }

            // Separate moves into direct assignments (old owner is dead) and
            // handoffs (old owner is alive and needs the handoff protocol).
            let mut moving_partitions: HashSet<u32> = HashSet::new();
            for (partition, old_owner, new_owner) in moves {
                moving_partitions.insert(partition);
                if registered_set.contains(old_owner.as_str()) {
                    all_handoffs.push(HandoffState {
                        topic: config.topic.clone(),
                        partition,
                        old_owner,
                        new_owner,
                        phase: HandoffPhase::Warming,
                        started_at: now,
                    });
                } else {
                    tracing::info!(
                        topic = %config.topic,
                        partition,
                        old_owner = %old_owner,
                        new_owner = %new_owner,
                        "old owner is dead, assigning directly without handoff"
                    );
                    all_assignments.push(PartitionAssignment {
                        topic: config.topic.clone(),
                        partition,
                        owner: new_owner,
                        status: AssignmentStatus::Active,
                    });
                }
            }

            // Stable assignments: partitions not moving
            for (&partition, owner) in &desired {
                if !moving_partitions.contains(&partition) {
                    all_assignments.push(PartitionAssignment {
                        topic: config.topic.clone(),
                        partition,
                        owner: owner.clone(),
                        status: AssignmentStatus::Active,
                    });
                }
            }
        }

        // No-op fast path: desired matches current for all topics.
        if !has_changes {
            tracing::debug!("assignments unchanged, skipping write");
            return Ok(());
        }

        if all_assignments.is_empty() && all_handoffs.is_empty() {
            tracing::debug!("no assignments or handoffs needed");
            return Ok(());
        }

        if all_handoffs.is_empty() {
            tracing::info!(assignments = all_assignments.len(), "writing assignments");
            store.put_assignments(&all_assignments).await?;
        } else {
            tracing::info!(
                assignments = all_assignments.len(),
                handoffs = all_handoffs.len(),
                "creating assignments and handoffs"
            );
            store
                .create_assignments_and_handoffs(&all_assignments, &all_handoffs)
                .await?;
        }

        Ok(())
    }

    /// Delete handoffs that can no longer make progress.
    ///
    /// Three cases:
    /// - `new_owner` is dead: the handoff can't complete (nobody to warm up).
    /// - `old_owner` is dead AND phase is `Complete`: the assignment is already
    ///   transferred, but nobody will call `PartitionReleased` to delete the
    ///   handoff. Without cleanup, this blocks all future rebalancing.
    /// - Handoff has exceeded the timeout: the consumer may be stuck or
    ///   non-responsive. Abort to unblock rebalancing.
    async fn cleanup_stale_handoffs(
        store: &KafkaAssignerStore,
        active_consumers: &[String],
        handoff_timeout: Duration,
    ) -> Result<()> {
        let handoffs = store.list_handoffs().await?;
        let active_set: HashSet<&str> = active_consumers.iter().map(|s| s.as_str()).collect();
        let now = util::now_seconds();
        let timeout_secs = handoff_timeout.as_secs() as i64;

        for handoff in &handoffs {
            let new_owner_dead = !active_set.contains(handoff.new_owner.as_str());
            let old_owner_dead_at_complete = handoff.phase == HandoffPhase::Complete
                && !active_set.contains(handoff.old_owner.as_str());
            let timed_out = (now - handoff.started_at) > timeout_secs;

            if new_owner_dead || old_owner_dead_at_complete || timed_out {
                tracing::warn!(
                    topic = %handoff.topic,
                    partition = handoff.partition,
                    old_owner = %handoff.old_owner,
                    new_owner = %handoff.new_owner,
                    phase = ?handoff.phase,
                    new_owner_dead,
                    old_owner_dead_at_complete,
                    timed_out,
                    "cleaning up stale handoff"
                );
                store.delete_handoff(&handoff.topic_partition()).await?;
            }
        }

        Ok(())
    }
}

// ── Pure functions ──────────────────────────────────────────────

/// Extract sorted consumer names, filtering to Ready status only.
/// Use for assignment computation (only Ready consumers get new partitions).
fn active_consumer_names(consumers: &[RegisteredConsumer]) -> Vec<String> {
    let mut active: Vec<&RegisteredConsumer> = consumers
        .iter()
        .filter(|c| c.status == ConsumerStatus::Ready)
        .collect();
    active.sort_by(|a, b| a.consumer_name.cmp(&b.consumer_name));
    active.iter().map(|c| c.consumer_name.clone()).collect()
}

/// Extract sorted names of all registered consumers regardless of status.
/// Use for liveness checks (a Draining consumer is still alive).
fn registered_consumer_names(consumers: &[RegisteredConsumer]) -> Vec<String> {
    let mut names: Vec<String> = consumers.iter().map(|c| c.consumer_name.clone()).collect();
    names.sort();
    names
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_consumer(name: &str) -> RegisteredConsumer {
        RegisteredConsumer {
            consumer_name: name.to_string(),
            status: ConsumerStatus::Ready,
            registered_at: 0,
        }
    }

    #[test]
    fn active_consumer_names_filters_and_sorts() {
        let mut draining = make_consumer("c-0");
        draining.status = ConsumerStatus::Draining;
        let consumers = vec![make_consumer("c-2"), draining, make_consumer("c-1")];
        let names = active_consumer_names(&consumers);
        assert_eq!(names, vec!["c-1", "c-2"]);
    }
}
