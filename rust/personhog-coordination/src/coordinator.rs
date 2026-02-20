use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use etcd_client::EventType;
use tokio_util::sync::CancellationToken;

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
}

impl Default for CoordinatorConfig {
    fn default() -> Self {
        Self {
            name: "coordinator-0".to_string(),
            leader_lease_ttl: 15,
            keepalive_interval: Duration::from_secs(5),
            election_retry_interval: Duration::from_secs(5),
            rebalance_debounce_interval: Duration::from_secs(1),
        }
    }
}

pub struct Coordinator {
    store: Arc<PersonhogStore>,
    config: CoordinatorConfig,
    strategy: Arc<dyn AssignmentStrategy>,
}

impl Coordinator {
    pub fn new(
        store: Arc<PersonhogStore>,
        config: CoordinatorConfig,
        strategy: Arc<dyn AssignmentStrategy>,
    ) -> Self {
        Self {
            store,
            config,
            strategy,
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
        // Compute initial assignments for any pods that are already registered
        self.handle_pod_change().await?;

        // Watch pods, handoffs, and router acks concurrently
        let mut tasks = tokio::task::JoinSet::new();

        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let debounce_interval = self.config.rebalance_debounce_interval;
            let token = cancel.child_token();
            tasks.spawn(async move {
                Self::watch_pods_loop(store, strategy, debounce_interval, token).await
            });
        }

        {
            let store = Arc::clone(&self.store);
            let strategy = Arc::clone(&self.strategy);
            let token = cancel.child_token();
            tasks.spawn(async move { Self::watch_handoffs_loop(store, strategy, token).await });
        }

        {
            let store = Arc::clone(&self.store);
            let token = cancel.child_token();
            tasks.spawn(async move { Self::watch_handoff_acks_loop(store, token).await });
        }

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
        debounce_interval: Duration,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_pods().await?;

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

            Self::handle_pod_change_static(&store, strategy.as_ref()).await?;
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
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_handoffs().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("handoff watch stream ended".to_string()))?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            match store::parse_watch_value::<HandoffState>(event) {
                                Ok(handoff) => {
                                    Self::handle_handoff_update_static(&store, &handoff).await?;
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
                        Self::handle_pod_change_static(&store, strategy.as_ref()).await?;
                    }
                }
            }
        }
    }

    /// Watch for router cutover acks. When all registered routers have acked
    /// a partition's handoff, complete the handoff (update assignment + phase).
    async fn watch_handoff_acks_loop(
        store: Arc<PersonhogStore>,
        cancel: CancellationToken,
    ) -> Result<()> {
        let mut stream = store.watch_handoff_acks().await?;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                msg = stream.message() => {
                    let resp = msg?.ok_or_else(|| Error::invalid_state("ack watch stream ended".to_string()))?;
                    for event in resp.events() {
                        if event.event_type() == EventType::Put {
                            // Extract partition from the ack key
                            let partition = event.kv().and_then(|kv| {
                                let key = std::str::from_utf8(kv.key()).ok()?;
                                store::extract_partition_from_ack_key(key)
                            });

                            if let Some(partition) = partition {
                                Self::check_ack_completion(&store, partition).await?;
                            }
                        }
                    }
                }
            }
        }
    }

    /// Check if all routers have acked a partition handoff.
    /// If so, atomically complete the handoff.
    async fn check_ack_completion(store: &PersonhogStore, partition: u32) -> Result<()> {
        let routers = store.list_routers().await?;
        if routers.is_empty() {
            tracing::warn!(partition, "no routers registered, cannot complete handoff");
            return Ok(());
        }

        let acks = store.list_router_acks(partition).await?;

        if acks.len() >= routers.len() {
            tracing::info!(
                partition,
                acks = acks.len(),
                routers = routers.len(),
                "all routers acked, completing handoff"
            );
            match store.complete_handoff(partition).await {
                Ok(true) => {}
                Ok(false) => {
                    tracing::warn!(partition, "handoff was modified concurrently, skipping");
                }
                Err(Error::NotFound(_)) => {
                    tracing::warn!(partition, "handoff already deleted, ignoring duplicate ack");
                }
                Err(e) => return Err(e),
            }
        }

        Ok(())
    }

    /// Handle a pod registration/deletion by recomputing assignments.
    async fn handle_pod_change(&self) -> Result<()> {
        Self::handle_pod_change_static(&self.store, self.strategy.as_ref()).await
    }

    async fn handle_pod_change_static(
        store: &PersonhogStore,
        strategy: &dyn AssignmentStrategy,
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

        let active_pods = active_pod_names(&pods);

        // Clean up any in-flight handoffs targeting pods that are no longer active.
        // This happens when a pod crashes during the Warming phase before it can
        // signal Ready — the handoff would be stuck forever otherwise.
        Self::cleanup_stale_handoffs(store, &active_pods).await?;

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
        let handoffs = compute_required_handoffs(&current_map, &new_assignments);

        if handoffs.is_empty() && !current_map.is_empty() {
            tracing::debug!("no handoffs needed");
            return Ok(());
        }

        // Build assignment objects for all partitions
        let assignment_objects: Vec<PartitionAssignment> = new_assignments
            .iter()
            .map(|(&partition, owner)| PartitionAssignment {
                partition,
                owner: owner.clone(),
                status: AssignmentStatus::Active,
            })
            .collect();

        if handoffs.is_empty() {
            // Initial assignment, no handoffs needed
            tracing::info!(
                partitions = total_partitions,
                pods = pods.len(),
                "writing initial assignments"
            );
            store.put_assignments(&assignment_objects).await?;
            return Ok(());
        }

        // Create handoff states for partitions that need to move
        let now = util::now_seconds();
        let handoff_objects: Vec<HandoffState> = handoffs
            .iter()
            .map(|(partition, old_owner, new_owner)| HandoffState {
                partition: *partition,
                old_owner: old_owner.clone(),
                new_owner: new_owner.clone(),
                phase: HandoffPhase::Warming,
                started_at: now,
            })
            .collect();

        tracing::info!(
            handoffs = handoff_objects.len(),
            "creating handoffs for partition reassignment"
        );

        // Only write assignments for partitions that are NOT being handed off.
        // Handed-off partitions keep their current assignment until cutover.
        let handoff_partitions: std::collections::HashSet<u32> =
            handoffs.iter().map(|(p, _, _)| *p).collect();
        let stable_assignments: Vec<PartitionAssignment> = assignment_objects
            .into_iter()
            .filter(|a| !handoff_partitions.contains(&a.partition))
            .collect();

        store
            .create_assignments_and_handoffs(&stable_assignments, &handoff_objects)
            .await?;

        Ok(())
    }

    /// Delete handoffs whose `new_owner` is no longer an active pod.
    async fn cleanup_stale_handoffs(store: &PersonhogStore, active_pods: &[String]) -> Result<()> {
        let handoffs = store.list_handoffs().await?;
        let active_set: std::collections::HashSet<&str> =
            active_pods.iter().map(|s| s.as_str()).collect();

        for handoff in &handoffs {
            if !active_set.contains(handoff.new_owner.as_str()) {
                tracing::warn!(
                    partition = handoff.partition,
                    new_owner = %handoff.new_owner,
                    phase = ?handoff.phase,
                    "cleaning up stale handoff targeting dead pod"
                );
                store.delete_router_acks(handoff.partition).await?;
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
            store.delete_router_acks(handoff.partition).await?;
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

/// Compare current and desired assignments to find needed handoffs.
///
/// Returns `(partition, old_owner, new_owner)` for each partition that needs
/// to move.
pub fn compute_required_handoffs(
    current: &HashMap<u32, String>,
    new: &HashMap<u32, String>,
) -> Vec<(u32, String, String)> {
    let mut handoffs = Vec::new();

    for (partition, new_owner) in new {
        if let Some(old_owner) = current.get(partition) {
            if old_owner != new_owner {
                handoffs.push((*partition, old_owner.clone(), new_owner.clone()));
            }
        }
    }

    handoffs
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_pod(name: &str) -> RegisteredPod {
        RegisteredPod {
            pod_name: name.to_string(),
            generation: "blue".to_string(),
            status: PodStatus::Ready,
            registered_at: 0,
            last_heartbeat: 0,
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

    #[test]
    fn compute_required_handoffs_no_change() {
        let mut current = HashMap::new();
        current.insert(0, "pod-0".to_string());
        current.insert(1, "pod-1".to_string());
        let new = current.clone();
        assert!(compute_required_handoffs(&current, &new).is_empty());
    }

    #[test]
    fn compute_required_handoffs_detects_moves() {
        let mut current = HashMap::new();
        current.insert(0, "pod-0".to_string());
        current.insert(1, "pod-0".to_string());

        let mut new = HashMap::new();
        new.insert(0, "pod-0".to_string());
        new.insert(1, "pod-1".to_string());

        let handoffs = compute_required_handoffs(&current, &new);
        assert_eq!(handoffs.len(), 1);
        assert_eq!(handoffs[0], (1, "pod-0".to_string(), "pod-1".to_string()));
    }

    #[test]
    fn compute_required_handoffs_new_partitions_ignored() {
        let current = HashMap::new();
        let mut new = HashMap::new();
        new.insert(0, "pod-0".to_string());
        assert!(compute_required_handoffs(&current, &new).is_empty());
    }
}
