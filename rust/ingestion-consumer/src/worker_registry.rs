use std::collections::VecDeque;
use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use metrics::{counter, gauge, histogram};
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::config::Config;

const PASSIVE_WINDOW_MAX_ENTRIES: usize = 10_000;

/// Stable identity for a worker: its base HTTP URL (e.g. `http://10.0.0.1:9001`).
/// Used as the key for health, routing pins, and in-flight load so the worker
/// set can change at runtime without the index-shifting hazards of a `Vec`.
pub type WorkerId = Arc<str>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerState {
    Healthy,
    Degraded,
    Unhealthy,
}

impl WorkerState {
    const ALL: [WorkerState; 3] = [
        WorkerState::Healthy,
        WorkerState::Degraded,
        WorkerState::Unhealthy,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            WorkerState::Healthy => "healthy",
            WorkerState::Degraded => "degraded",
            WorkerState::Unhealthy => "unhealthy",
        }
    }
}

/// Emit the worker health state as a state-set gauge: one series per state
/// labeled `state`, with the current state at 1 and all others at 0 (same
/// pattern as `kube_pod_status_phase`). Operators can alert on a state by
/// name without decoding magic numbers.
fn set_state_gauge(worker_url: &str, current: WorkerState) {
    for state in WorkerState::ALL {
        gauge!(
            "ingestion_consumer_worker_health_state",
            "worker" => worker_url.to_string(),
            "state" => state.as_str(),
        )
        .set(if state == current { 1.0 } else { 0.0 });
    }
}

/// Clear the state-set gauge for a worker that has left the pool, so a departed
/// worker doesn't linger at 1 in dashboards.
fn clear_state_gauge(worker_url: &str) {
    for state in WorkerState::ALL {
        gauge!(
            "ingestion_consumer_worker_health_state",
            "worker" => worker_url.to_string(),
            "state" => state.as_str(),
        )
        .set(0.0);
    }
}

/// Per-worker mutable health state.
struct WorkerHealth {
    state: WorkerState,
    state_entered_at: Instant,
    /// When the worker entered Unhealthy. None if the worker is not currently Unhealthy.
    unhealthy_since: Option<Instant>,
    consecutive_probe_failures: u32,
    /// Rolling window of passive send outcomes: (timestamp, is_error).
    /// Always appended in chronological order so the head is always the oldest entry.
    passive_window: VecDeque<(Instant, bool)>,
    /// The worker is draining: it left the pool (e.g. a deploy) but may still be
    /// finishing in-flight batches. It receives no new work and its `/_ready`
    /// probe failures are ignored (readiness is expected to be down), but send
    /// failures still escalate it (a crash mid-drain). It is reaped once
    /// `drain_deadline` passes — set to "now" when its in-flight reaches zero.
    drain_deadline: Option<Instant>,
}

impl WorkerHealth {
    fn new() -> Self {
        Self {
            state: WorkerState::Healthy,
            state_entered_at: Instant::now(),
            unhealthy_since: None,
            consecutive_probe_failures: 0,
            passive_window: VecDeque::new(),
            drain_deadline: None,
        }
    }

    fn is_draining(&self) -> bool {
        self.drain_deadline.is_some()
    }

    /// Attempt a state transition. Returns true if the transition happened.
    ///
    /// Transitions to the same state are ignored. Transitions within
    /// `min_state_duration` of the last transition are blocked to prevent
    /// flapping.
    fn try_transition(
        &mut self,
        new_state: WorkerState,
        min_state_duration: Duration,
        worker_url: &str,
    ) -> bool {
        if self.state == new_state {
            return false;
        }

        if self.state_entered_at.elapsed() < min_state_duration {
            return false;
        }

        let old_state = self.state;
        self.state = new_state;
        self.state_entered_at = Instant::now();
        // Reset so probe failure count is always scoped to the current state
        // epoch. Without this, a passive-driven transition (e.g. Healthy →
        // Degraded) carries the stale count into the new state, effectively
        // lowering the probe_failure_threshold by however many failures had
        // already accumulated.
        self.consecutive_probe_failures = 0;

        if new_state == WorkerState::Unhealthy && self.unhealthy_since.is_none() {
            self.unhealthy_since = Some(Instant::now());
        } else if new_state != WorkerState::Unhealthy {
            self.unhealthy_since = None;
        }

        info!(
            worker = %worker_url,
            from = old_state.as_str(),
            to = new_state.as_str(),
            "Worker state transition"
        );
        counter!(
            "ingestion_consumer_worker_state_transitions_total",
            "worker" => worker_url.to_string(),
            "from" => old_state.as_str(),
            "to" => new_state.as_str(),
        )
        .increment(1);
        set_state_gauge(worker_url, new_state);

        true
    }

    fn is_dead(&self, dead_declaration: Duration) -> bool {
        self.state == WorkerState::Unhealthy
            && self
                .unhealthy_since
                .is_some_and(|t| t.elapsed() >= dead_declaration)
    }

    /// Prune passive window entries older than `window` and return
    /// `(error_rate, sample_count)` over the remaining entries.
    fn passive_error_rate(&mut self, window: Duration) -> (f64, usize) {
        let now = Instant::now();
        while let Some((t, _)) = self.passive_window.front() {
            if now.saturating_duration_since(*t) > window {
                self.passive_window.pop_front();
            } else {
                break;
            }
        }

        let total = self.passive_window.len();
        if total == 0 {
            return (0.0, 0);
        }

        let errors = self
            .passive_window
            .iter()
            .filter(|(_, is_err)| *is_err)
            .count();
        (errors as f64 / total as f64, total)
    }
}

pub struct WorkerRegistryConfig {
    pub probe_interval: Duration,
    pub dead_declaration: Duration,
    pub passive_window: Duration,
    pub passive_error_threshold: f64,
    pub passive_min_samples: usize,
    pub degraded_hold: Duration,
    pub min_state_duration: Duration,
    pub probe_failure_threshold: u32,
    pub drain_timeout: Duration,
}

impl From<&Config> for WorkerRegistryConfig {
    fn from(c: &Config) -> Self {
        Self {
            probe_interval: Duration::from_millis(c.worker_probe_interval_ms),
            dead_declaration: Duration::from_millis(c.worker_dead_declaration_ms),
            passive_window: Duration::from_millis(c.worker_passive_window_ms),
            passive_error_threshold: c.worker_passive_error_threshold,
            passive_min_samples: c.worker_passive_min_samples,
            degraded_hold: Duration::from_millis(c.worker_degraded_hold_ms),
            min_state_duration: Duration::from_millis(c.worker_min_state_duration_ms),
            probe_failure_threshold: c.worker_probe_failure_threshold,
            drain_timeout: Duration::from_millis(c.worker_drain_timeout_ms),
        }
    }
}

/// Tracks the health state of each Node.js worker, keyed by worker URL so the
/// set can change at runtime (workers joining/leaving the pool). Uses two
/// independent signals:
///
/// - **Active probe**: GET `/_ready` every `probe_interval`. Two consecutive
///   failures move the worker to `Unhealthy`; one success starts the recovery
///   to `Degraded` (held for `degraded_hold`), then `Healthy`.
/// - **Passive signal**: rolling window of `send_batch` outcomes. If error rate
///   exceeds `passive_error_threshold` with at least `passive_min_samples`
///   samples, the worker moves one step toward `Unhealthy`. Only probe success
///   drives recovery.
///
/// All transitions respect a `min_state_duration` cooldown to prevent flapping.
///
/// A worker that has been `Unhealthy` for at least `dead_declaration` is
/// considered **dead** — the Dispatcher uses this to drop sticky pins so the
/// next batch can re-route around the worker. A worker removed from the pool
/// entirely is also reported dead.
pub struct WorkerRegistry {
    workers: DashMap<WorkerId, WorkerHealth>,
    config: WorkerRegistryConfig,
    client: reqwest::Client,
}

impl WorkerRegistry {
    pub fn new(worker_urls: &[String], config: WorkerRegistryConfig) -> Self {
        // Probe timeout is half the probe interval so probes don't overlap.
        let probe_timeout = config.probe_interval / 2;
        let client = reqwest::Client::builder()
            .timeout(probe_timeout)
            .build()
            .expect("failed to create probe HTTP client");

        let workers = DashMap::new();
        for url in worker_urls {
            workers.insert(WorkerId::from(url.as_str()), WorkerHealth::new());
            // Emit the initial state so the gauge exists from startup rather
            // than only after the first transition.
            set_state_gauge(url, WorkerState::Healthy);
        }

        Self {
            workers,
            config,
            client,
        }
    }

    pub fn worker_count(&self) -> usize {
        self.workers.len()
    }

    /// Snapshot of all current worker ids.
    pub fn workers(&self) -> Vec<WorkerId> {
        self.workers.iter().map(|e| e.key().clone()).collect()
    }

    /// Snapshot of worker ids currently eligible for routing: Healthy or
    /// Degraded, and not draining. Returned in arbitrary order.
    pub fn healthy_workers(&self) -> Vec<WorkerId> {
        self.workers
            .iter()
            .filter(|e| {
                !e.value().is_draining()
                    && matches!(
                        e.value().state,
                        WorkerState::Healthy | WorkerState::Degraded
                    )
            })
            .map(|e| e.key().clone())
            .collect()
    }

    /// Current state of a worker. An unknown worker (already removed from the
    /// pool) reports `Unhealthy` so callers never route to it.
    pub fn state(&self, worker: &str) -> WorkerState {
        self.workers
            .get(worker)
            .map(|h| h.state)
            .unwrap_or(WorkerState::Unhealthy)
    }

    /// Whether a worker is dead — Unhealthy for at least `dead_declaration`, or
    /// no longer in the pool at all (so its sticky pins get dropped).
    pub fn is_dead(&self, worker: &str) -> bool {
        self.workers
            .get(worker)
            .map(|h| h.is_dead(self.config.dead_declaration))
            .unwrap_or(true)
    }

    /// Add a worker to the pool. If it is already present and draining (it left
    /// and rejoined, e.g. a flapping EndpointSlice), clear the draining mark so
    /// it routes again; otherwise an existing worker keeps its current health.
    pub fn add_worker(&self, worker: WorkerId) {
        // `entry` makes the check-and-insert atomic — a plain `contains_key` +
        // `insert` could let a concurrent caller overwrite a fresh `WorkerHealth`
        // and reset health state.
        match self.workers.entry(worker.clone()) {
            Entry::Occupied(mut slot) => {
                // Already present. If it was draining (it left and rejoined, e.g.
                // a flapping EndpointSlice), clear the draining mark so it routes
                // again; otherwise it keeps its current health.
                if slot.get_mut().drain_deadline.take().is_some() {
                    info!(worker = %worker, "Draining worker rejoined the pool");
                }
            }
            Entry::Vacant(slot) => {
                set_state_gauge(&worker, WorkerState::Healthy);
                info!(worker = %worker, "Worker added to pool");
                slot.insert(WorkerHealth::new());
                counter!("ingestion_consumer_worker_membership_total", "action" => "add")
                    .increment(1);
            }
        }
    }

    /// Mark a worker as draining: it stops receiving new work (excluded from
    /// `healthy_workers`) but is not treated as dead, so its already-sent
    /// in-flight batches finish and ACK normally. Probe failures are ignored
    /// while draining (its readiness is expected to be down), but send failures
    /// still escalate it (a crash mid-drain). The reaper removes it once
    /// `complete_drain` fires (in-flight reached zero) or `drain_timeout` elapses.
    pub fn start_draining(&self, worker: &str) {
        if let Some(mut health) = self.workers.get_mut(worker) {
            if health.is_draining() {
                return;
            }
            health.drain_deadline = Some(Instant::now() + self.config.drain_timeout);
            info!(worker = %worker, "Worker draining (no new work; finishing in-flight)");
            counter!("ingestion_consumer_worker_membership_total", "action" => "drain")
                .increment(1);
        }
    }

    /// Mark a draining worker ready to reap now — called once its in-flight count
    /// reaches zero, so it's removed promptly instead of waiting for the timeout.
    pub fn complete_drain(&self, worker: &str) {
        if let Some(mut health) = self.workers.get_mut(worker) {
            if health.is_draining() {
                health.drain_deadline = Some(Instant::now());
            }
        }
    }

    pub fn is_draining(&self, worker: &str) -> bool {
        self.workers
            .get(worker)
            .map(|h| h.is_draining())
            .unwrap_or(false)
    }

    /// Draining workers whose reap deadline has passed (in-flight drained, or the
    /// timeout elapsed). The caller removes them from the registry and transport.
    pub fn reapable_workers(&self) -> Vec<WorkerId> {
        let now = Instant::now();
        self.workers
            .iter()
            .filter(|e| e.value().drain_deadline.is_some_and(|d| now >= d))
            .map(|e| e.key().clone())
            .collect()
    }

    /// All workers currently draining (regardless of deadline). The reaper uses
    /// this to complete the drain of a worker that left the pool while idle.
    pub fn draining_workers(&self) -> Vec<WorkerId> {
        self.workers
            .iter()
            .filter(|e| e.value().is_draining())
            .map(|e| e.key().clone())
            .collect()
    }

    /// Remove a worker from the pool (e.g. it left the EndpointSlice).
    pub fn remove_worker(&self, worker: &str) {
        if self.workers.remove(worker).is_some() {
            clear_state_gauge(worker);
            info!(worker = %worker, "Worker removed from pool");
            counter!("ingestion_consumer_worker_membership_total", "action" => "remove")
                .increment(1);
        }
    }

    /// Record the outcome of a `send_batch` call for the passive signal.
    pub fn record_outcome(&self, worker: &str, is_error: bool) {
        let Some(mut health) = self.workers.get_mut(worker) else {
            return;
        };

        health.passive_window.push_back((Instant::now(), is_error));
        if health.passive_window.len() > PASSIVE_WINDOW_MAX_ENTRIES {
            health.passive_window.pop_front();
        }

        let (error_rate, sample_count) = health.passive_error_rate(self.config.passive_window);
        gauge!(
            "ingestion_consumer_worker_passive_error_rate",
            "worker" => worker.to_string(),
        )
        .set(error_rate);

        if sample_count >= self.config.passive_min_samples
            && error_rate > self.config.passive_error_threshold
        {
            let target = match health.state {
                WorkerState::Healthy => Some(WorkerState::Degraded),
                WorkerState::Degraded => Some(WorkerState::Unhealthy),
                WorkerState::Unhealthy => None,
            };
            if let Some(new_state) = target {
                health.try_transition(new_state, self.config.min_state_duration, worker);
            }
        }
    }

    /// Spawn a single background task that probes every current worker each
    /// `probe_interval`. Runs until `token` is cancelled. The worker set is
    /// re-read each tick, so workers added/removed at runtime are picked up.
    pub fn start_probing(self: Arc<Self>, token: CancellationToken) {
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = token.cancelled() => break,
                    _ = tokio::time::sleep(self.config.probe_interval) => {}
                }

                let workers = self.workers();
                let probes = workers.into_iter().map(|worker| {
                    let registry = Arc::clone(&self);
                    async move { registry.probe_once(&worker).await }
                });
                futures::future::join_all(probes).await;
            }
        });
    }

    async fn probe_once(&self, worker: &str) {
        let start = Instant::now();
        let result = self.client.get(format!("{worker}/_ready")).send().await;
        let elapsed = start.elapsed();
        let is_success = result.map(|r| r.status().is_success()).unwrap_or(false);

        histogram!(
            "ingestion_consumer_worker_probe_duration_seconds",
            "worker" => worker.to_string(),
            "outcome" => if is_success { "success" } else { "failure" },
        )
        .record(elapsed.as_secs_f64());

        // The worker may have been removed between the snapshot and now.
        let Some(mut health) = self.workers.get_mut(worker) else {
            return;
        };

        // A draining worker's `/_ready` is expected to be down (it flipped
        // readiness to leave the pool), so ignore probe results — otherwise the
        // probe would march it to dead and evict its in-flight work. A crash
        // mid-drain is still caught by the passive send-failure signal.
        if health.is_draining() {
            return;
        }

        if is_success {
            health.consecutive_probe_failures = 0;

            let new_state = match health.state {
                WorkerState::Unhealthy => Some(WorkerState::Degraded),
                WorkerState::Degraded => {
                    if health.state_entered_at.elapsed() >= self.config.degraded_hold {
                        Some(WorkerState::Healthy)
                    } else {
                        None
                    }
                }
                WorkerState::Healthy => None,
            };
            if let Some(s) = new_state {
                health.try_transition(s, self.config.min_state_duration, worker);
            }
        } else {
            health.consecutive_probe_failures += 1;
            warn!(
                worker = %worker,
                consecutive_failures = health.consecutive_probe_failures,
                "Worker probe failed"
            );
            if health.consecutive_probe_failures >= self.config.probe_failure_threshold {
                health.try_transition(
                    WorkerState::Unhealthy,
                    self.config.min_state_duration,
                    worker,
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    const W1: &str = "http://worker:9001";
    const W2: &str = "http://worker:9002";
    const W3: &str = "http://worker:9003";

    fn no_cooldown_config() -> WorkerRegistryConfig {
        WorkerRegistryConfig {
            probe_interval: Duration::from_millis(50),
            dead_declaration: Duration::from_millis(100),
            passive_window: Duration::from_millis(500),
            passive_error_threshold: 0.5,
            passive_min_samples: 3,
            degraded_hold: Duration::from_millis(50),
            min_state_duration: Duration::ZERO,
            probe_failure_threshold: 2,
            drain_timeout: Duration::from_secs(5),
        }
    }

    fn one_worker() -> Vec<String> {
        vec![W1.to_string()]
    }

    fn three_workers() -> Vec<String> {
        vec![W1.to_string(), W2.to_string(), W3.to_string()]
    }

    // --- Passive signal transitions ---

    #[test]
    fn test_passive_healthy_to_degraded() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());

        // 3 errors = 100% error rate, 3 samples ≥ min_samples=3, rate > threshold=0.5
        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);

        assert_eq!(registry.state(W1), WorkerState::Degraded);
    }

    #[test]
    fn test_passive_degraded_to_unhealthy() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());

        for _ in 0..3 {
            registry.record_outcome(W1, true);
        }
        assert_eq!(registry.state(W1), WorkerState::Degraded);

        // One more error pushes Degraded → Unhealthy (still above threshold)
        registry.record_outcome(W1, true);
        assert_eq!(registry.state(W1), WorkerState::Unhealthy);
    }

    #[test]
    fn test_passive_below_threshold_stays_healthy() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());

        // 1 error out of 3 = 33% < threshold=50%
        registry.record_outcome(W1, true);
        registry.record_outcome(W1, false);
        registry.record_outcome(W1, false);

        assert_eq!(registry.state(W1), WorkerState::Healthy);
    }

    #[test]
    fn test_passive_below_min_samples_stays_healthy() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());

        // 2 errors but only 2 samples < min_samples=3
        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);

        assert_eq!(registry.state(W1), WorkerState::Healthy);
    }

    #[test]
    fn test_passive_unhealthy_stays_unhealthy() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());

        for _ in 0..4 {
            registry.record_outcome(W1, true);
        }
        assert_eq!(registry.state(W1), WorkerState::Unhealthy);

        registry.record_outcome(W1, true);
        assert_eq!(registry.state(W1), WorkerState::Unhealthy);
    }

    // --- Cooldown ---

    #[test]
    fn test_cooldown_blocks_transition() {
        let config = WorkerRegistryConfig {
            min_state_duration: Duration::from_secs(100),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&one_worker(), config);

        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);

        assert_eq!(registry.state(W1), WorkerState::Healthy);
    }

    // --- Probe-driven transitions (via direct WorkerHealth manipulation) ---

    #[test]
    fn test_probe_failures_to_unhealthy() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        let mut health = registry.workers.get_mut(W1).unwrap();

        health.consecutive_probe_failures = 2;
        let transitioned = health.try_transition(WorkerState::Unhealthy, Duration::ZERO, W1);

        assert!(transitioned);
        assert_eq!(health.state, WorkerState::Unhealthy);
        assert!(health.unhealthy_since.is_some());
    }

    #[test]
    fn test_probe_success_unhealthy_to_degraded() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        let mut health = registry.workers.get_mut(W1).unwrap();

        health.try_transition(WorkerState::Unhealthy, Duration::ZERO, W1);
        assert_eq!(health.state, WorkerState::Unhealthy);

        let transitioned = health.try_transition(WorkerState::Degraded, Duration::ZERO, W1);

        assert!(transitioned);
        assert_eq!(health.state, WorkerState::Degraded);
        assert!(health.unhealthy_since.is_none());
    }

    #[test]
    fn test_probe_failure_threshold_not_reached() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        let health = registry.workers.get(W1).unwrap();

        assert_eq!(health.state, WorkerState::Healthy);
    }

    // --- Dead declaration ---

    #[tokio::test]
    async fn test_dead_declaration_fires_after_duration() {
        let config = WorkerRegistryConfig {
            dead_declaration: Duration::from_millis(30),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&one_worker(), config);

        for _ in 0..4 {
            registry.record_outcome(W1, true);
        }
        assert_eq!(registry.state(W1), WorkerState::Unhealthy);
        assert!(!registry.is_dead(W1));

        tokio::time::sleep(Duration::from_millis(40)).await;
        assert!(registry.is_dead(W1));
    }

    #[test]
    fn test_healthy_worker_is_not_dead() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        assert!(!registry.is_dead(W1));
    }

    // --- Membership ---

    #[test]
    fn test_unknown_worker_is_dead_and_unhealthy() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        assert!(registry.is_dead("http://worker:9999"));
        assert_eq!(registry.state("http://worker:9999"), WorkerState::Unhealthy);
    }

    #[test]
    fn test_add_worker_makes_it_healthy_and_routable() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        assert_eq!(registry.worker_count(), 1);

        registry.add_worker(WorkerId::from(W2));
        assert_eq!(registry.worker_count(), 2);
        assert_eq!(registry.state(W2), WorkerState::Healthy);
        assert!(registry.healthy_workers().iter().any(|w| w.as_ref() == W2));
    }

    #[test]
    fn test_add_worker_is_idempotent_and_preserves_state() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        // Drive W1 to Degraded, then re-add it — must not reset to Healthy.
        for _ in 0..3 {
            registry.record_outcome(W1, true);
        }
        assert_eq!(registry.state(W1), WorkerState::Degraded);

        registry.add_worker(WorkerId::from(W1));
        assert_eq!(registry.worker_count(), 1);
        assert_eq!(registry.state(W1), WorkerState::Degraded);
    }

    #[test]
    fn test_remove_worker_drops_it_from_pool() {
        let registry = WorkerRegistry::new(&three_workers(), no_cooldown_config());
        registry.remove_worker(W2);

        assert_eq!(registry.worker_count(), 2);
        assert!(registry.is_dead(W2));
        assert!(!registry.healthy_workers().iter().any(|w| w.as_ref() == W2));
    }

    #[test]
    fn test_healthy_workers_excludes_unhealthy() {
        let registry = WorkerRegistry::new(&three_workers(), no_cooldown_config());
        for _ in 0..4 {
            registry.record_outcome(W2, true);
        }
        assert_eq!(registry.state(W2), WorkerState::Unhealthy);

        let healthy = registry.healthy_workers();
        assert_eq!(healthy.len(), 2);
        assert!(!healthy.iter().any(|w| w.as_ref() == W2));
    }

    // --- Draining lifecycle ---

    #[test]
    fn test_draining_excludes_from_routing_but_not_dead() {
        let registry = WorkerRegistry::new(&three_workers(), no_cooldown_config());
        registry.start_draining(W2);

        assert!(registry.is_draining(W2));
        assert!(
            !registry.is_dead(W2),
            "a draining worker is alive, not dead"
        );
        assert_eq!(
            registry.state(W2),
            WorkerState::Healthy,
            "draining doesn't change the health state"
        );
        assert!(
            !registry.healthy_workers().iter().any(|w| w.as_ref() == W2),
            "a draining worker is not routable"
        );
        assert_eq!(registry.worker_count(), 3, "still in the pool until reaped");
    }

    #[test]
    fn test_complete_drain_makes_reapable() {
        // Long timeout, so only complete_drain (in-flight reached zero) reaps it.
        let config = WorkerRegistryConfig {
            drain_timeout: Duration::from_secs(3600),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&three_workers(), config);
        registry.start_draining(W2);
        assert!(
            registry.reapable_workers().is_empty(),
            "not reapable until drained or timed out"
        );

        registry.complete_drain(W2);
        assert_eq!(registry.reapable_workers(), vec![WorkerId::from(W2)]);
    }

    #[tokio::test]
    async fn test_drain_timeout_makes_reapable() {
        let config = WorkerRegistryConfig {
            drain_timeout: Duration::from_millis(20),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&one_worker(), config);
        registry.start_draining(W1);
        assert!(registry.reapable_workers().is_empty());

        tokio::time::sleep(Duration::from_millis(30)).await;
        assert_eq!(registry.reapable_workers(), vec![WorkerId::from(W1)]);
    }

    #[test]
    fn test_add_worker_rejoin_clears_draining() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        registry.start_draining(W1);
        assert!(registry.is_draining(W1));

        registry.add_worker(WorkerId::from(W1));
        assert!(!registry.is_draining(W1), "rejoining clears draining");
        assert!(registry.healthy_workers().iter().any(|w| w.as_ref() == W1));
    }

    #[test]
    fn test_start_draining_unknown_worker_is_noop() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        registry.start_draining("http://worker:9999");
        assert!(!registry.is_draining("http://worker:9999"));
        assert!(registry.reapable_workers().is_empty());
    }

    // --- Passive window pruning ---

    #[tokio::test]
    async fn test_passive_window_prunes_old_entries() {
        let config = WorkerRegistryConfig {
            passive_window: Duration::from_millis(30),
            passive_min_samples: 2,
            passive_error_threshold: 0.5,
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&one_worker(), config);

        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);
        assert_eq!(registry.state(W1), WorkerState::Degraded);

        tokio::time::sleep(Duration::from_millis(40)).await;
        registry.record_outcome(W1, false);
        registry.record_outcome(W1, false);

        let (rate, count) = {
            let mut health = registry.workers.get_mut(W1).unwrap();
            health.passive_error_rate(Duration::from_millis(30))
        };

        assert_eq!(count, 2);
        assert_eq!(rate, 0.0);
    }

    // --- Multiple workers ---

    #[test]
    fn test_worker_count() {
        let registry = WorkerRegistry::new(&three_workers(), no_cooldown_config());
        assert_eq!(registry.worker_count(), 3);
    }

    #[test]
    fn test_states_are_independent_per_worker() {
        let registry = WorkerRegistry::new(&three_workers(), no_cooldown_config());

        for _ in 0..4 {
            registry.record_outcome(W2, true);
        }

        assert_eq!(registry.state(W1), WorkerState::Healthy);
        assert_eq!(registry.state(W2), WorkerState::Unhealthy);
        assert_eq!(registry.state(W3), WorkerState::Healthy);
    }

    #[tokio::test]
    async fn test_is_dead_is_per_worker() {
        let config = WorkerRegistryConfig {
            dead_declaration: Duration::from_millis(30),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&three_workers(), config);

        for _ in 0..4 {
            registry.record_outcome(W3, true);
        }

        tokio::time::sleep(Duration::from_millis(40)).await;

        assert!(!registry.is_dead(W1));
        assert!(!registry.is_dead(W2));
        assert!(registry.is_dead(W3));
    }

    // --- consecutive_probe_failures reset on transition ---

    #[test]
    fn test_probe_failure_count_reset_on_passive_transition() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());

        registry
            .workers
            .get_mut(W1)
            .unwrap()
            .consecutive_probe_failures = 1;

        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);
        registry.record_outcome(W1, true);
        assert_eq!(registry.state(W1), WorkerState::Degraded);

        assert_eq!(
            registry.workers.get(W1).unwrap().consecutive_probe_failures,
            0,
            "try_transition must reset consecutive_probe_failures so the Degraded epoch needs a full probe_failure_threshold failures to reach Unhealthy"
        );
    }

    // --- passive_window size cap ---

    #[test]
    fn test_passive_window_capped_at_max_entries() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());

        for _ in 0..PASSIVE_WINDOW_MAX_ENTRIES + 10 {
            registry.record_outcome(W1, false);
        }

        assert!(
            registry.workers.get(W1).unwrap().passive_window.len() <= PASSIVE_WINDOW_MAX_ENTRIES,
            "passive_window must not exceed PASSIVE_WINDOW_MAX_ENTRIES"
        );
    }

    // --- Same-state no-op ---

    #[test]
    fn test_transition_to_same_state_is_noop() {
        let registry = WorkerRegistry::new(&one_worker(), no_cooldown_config());
        let mut health = registry.workers.get_mut(W1).unwrap();

        let transitioned = health.try_transition(WorkerState::Healthy, Duration::ZERO, W1);

        assert!(!transitioned);
        assert_eq!(health.state, WorkerState::Healthy);
    }
}
