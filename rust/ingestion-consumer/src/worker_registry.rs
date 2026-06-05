use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use metrics::{counter, gauge, histogram};
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::config::Config;

const PASSIVE_WINDOW_MAX_ENTRIES: usize = 10_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerState {
    Healthy,
    Degraded,
    Unhealthy,
}

impl WorkerState {
    pub fn as_str(self) -> &'static str {
        match self {
            WorkerState::Healthy => "healthy",
            WorkerState::Degraded => "degraded",
            WorkerState::Unhealthy => "unhealthy",
        }
    }

    fn as_gauge_value(self) -> f64 {
        match self {
            WorkerState::Healthy => 0.0,
            WorkerState::Degraded => 1.0,
            WorkerState::Unhealthy => 2.0,
        }
    }
}

/// Per-worker mutable health state, behind a Mutex.
struct WorkerHealth {
    state: WorkerState,
    state_entered_at: Instant,
    /// When the worker entered Unhealthy. None if the worker is not currently Unhealthy.
    unhealthy_since: Option<Instant>,
    consecutive_probe_failures: u32,
    /// Rolling window of passive send outcomes: (timestamp, is_error).
    /// Always appended in chronological order so the head is always the oldest entry.
    passive_window: VecDeque<(Instant, bool)>,
}

impl WorkerHealth {
    fn new() -> Self {
        Self {
            state: WorkerState::Healthy,
            state_entered_at: Instant::now(),
            unhealthy_since: None,
            consecutive_probe_failures: 0,
            passive_window: VecDeque::new(),
        }
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
        // Numeric gauge so operators can alert directly on state without
        // reconstructing it from cumulative transition counters.
        // 0 = Healthy, 1 = Degraded, 2 = Unhealthy.
        gauge!(
            "ingestion_consumer_worker_health_state",
            "worker" => worker_url.to_string(),
        )
        .set(new_state.as_gauge_value());

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
        }
    }
}

/// Tracks the health state of each Node.js worker using two independent signals:
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
/// next batch can re-route around the worker.
pub struct WorkerRegistry {
    workers: Vec<(String, Mutex<WorkerHealth>)>,
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

        let workers = worker_urls
            .iter()
            .map(|url| (url.clone(), Mutex::new(WorkerHealth::new())))
            .collect();

        Self {
            workers,
            config,
            client,
        }
    }

    pub fn worker_count(&self) -> usize {
        self.workers.len()
    }

    pub fn state(&self, worker_idx: usize) -> WorkerState {
        self.workers[worker_idx].1.lock().unwrap().state
    }

    pub fn is_dead(&self, worker_idx: usize) -> bool {
        self.workers[worker_idx]
            .1
            .lock()
            .unwrap()
            .is_dead(self.config.dead_declaration)
    }

    /// Record the outcome of a `send_batch` call for the passive signal.
    pub fn record_outcome(&self, worker_idx: usize, is_error: bool) {
        let (url, health_lock) = &self.workers[worker_idx];
        let mut health = health_lock.lock().unwrap();

        health.passive_window.push_back((Instant::now(), is_error));
        if health.passive_window.len() > PASSIVE_WINDOW_MAX_ENTRIES {
            health.passive_window.pop_front();
        }

        let (error_rate, sample_count) = health.passive_error_rate(self.config.passive_window);
        gauge!(
            "ingestion_consumer_worker_passive_error_rate",
            "worker" => url.clone(),
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
                health.try_transition(new_state, self.config.min_state_duration, url);
            }
        }
    }

    /// Spawn a background probe task for each worker. The tasks run until
    /// `token` is cancelled. Call this on an `Arc<WorkerRegistry>` so each
    /// task can hold its own clone of the registry.
    pub fn start_probing(self: Arc<Self>, token: CancellationToken) {
        for idx in 0..self.workers.len() {
            let registry = self.clone();
            let token = token.clone();
            tokio::spawn(async move {
                registry.run_probe(idx, token).await;
            });
        }
    }

    async fn run_probe(&self, worker_idx: usize, token: CancellationToken) {
        let (url, _) = &self.workers[worker_idx];
        let url = url.clone();

        loop {
            tokio::select! {
                _ = token.cancelled() => break,
                _ = tokio::time::sleep(self.config.probe_interval) => {}
            }

            let start = Instant::now();
            let result = self.client.get(format!("{url}/_ready")).send().await;
            let elapsed = start.elapsed();
            let is_success = result.map(|r| r.status().is_success()).unwrap_or(false);

            histogram!(
                "ingestion_consumer_worker_probe_duration_seconds",
                "worker" => url.clone(),
                "outcome" => if is_success { "success" } else { "failure" },
            )
            .record(elapsed.as_secs_f64());

            let (worker_url, health_lock) = &self.workers[worker_idx];
            let mut health = health_lock.lock().unwrap();

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
                    health.try_transition(s, self.config.min_state_duration, worker_url);
                }
            } else {
                health.consecutive_probe_failures += 1;
                warn!(
                    worker = %worker_url,
                    consecutive_failures = health.consecutive_probe_failures,
                    "Worker probe failed"
                );
                if health.consecutive_probe_failures >= self.config.probe_failure_threshold {
                    health.try_transition(
                        WorkerState::Unhealthy,
                        self.config.min_state_duration,
                        worker_url,
                    );
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

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
        }
    }

    fn worker_urls() -> Vec<String> {
        vec!["http://worker:9001".to_string()]
    }

    fn multi_worker_urls() -> Vec<String> {
        vec![
            "http://worker:9001".to_string(),
            "http://worker:9002".to_string(),
            "http://worker:9003".to_string(),
        ]
    }

    // --- Passive signal transitions ---

    #[test]
    fn test_passive_healthy_to_degraded() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());

        // 3 errors = 100% error rate, 3 samples ≥ min_samples=3, rate > threshold=0.5
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);

        assert_eq!(registry.state(0), WorkerState::Degraded);
    }

    #[test]
    fn test_passive_degraded_to_unhealthy() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());

        // Reach Degraded
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);
        assert_eq!(registry.state(0), WorkerState::Degraded);

        // One more error pushes Degraded → Unhealthy (still above threshold)
        registry.record_outcome(0, true);
        assert_eq!(registry.state(0), WorkerState::Unhealthy);
    }

    #[test]
    fn test_passive_below_threshold_stays_healthy() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());

        // 1 error out of 3 = 33% < threshold=50%
        registry.record_outcome(0, true);
        registry.record_outcome(0, false);
        registry.record_outcome(0, false);

        assert_eq!(registry.state(0), WorkerState::Healthy);
    }

    #[test]
    fn test_passive_below_min_samples_stays_healthy() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());

        // 2 errors but only 2 samples < min_samples=3
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);

        assert_eq!(registry.state(0), WorkerState::Healthy);
    }

    #[test]
    fn test_passive_unhealthy_stays_unhealthy() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());

        // Drive to Unhealthy
        for _ in 0..4 {
            registry.record_outcome(0, true);
        }
        assert_eq!(registry.state(0), WorkerState::Unhealthy);

        // More errors don't change anything
        registry.record_outcome(0, true);
        assert_eq!(registry.state(0), WorkerState::Unhealthy);
    }

    // --- Cooldown ---

    #[test]
    fn test_cooldown_blocks_transition() {
        let config = WorkerRegistryConfig {
            min_state_duration: Duration::from_secs(100),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&worker_urls(), config);

        // Threshold crossed but cooldown blocks Healthy → Degraded
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);

        assert_eq!(registry.state(0), WorkerState::Healthy);
    }

    // --- Probe-driven transitions (via direct WorkerHealth manipulation) ---

    #[test]
    fn test_probe_failures_to_unhealthy() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());
        let (url, health_lock) = &registry.workers[0];
        let mut health = health_lock.lock().unwrap();

        // Simulate 2 consecutive probe failures
        health.consecutive_probe_failures = 2;
        let transitioned = health.try_transition(WorkerState::Unhealthy, Duration::ZERO, url);

        assert!(transitioned);
        assert_eq!(health.state, WorkerState::Unhealthy);
        assert!(health.unhealthy_since.is_some());
    }

    #[test]
    fn test_probe_success_unhealthy_to_degraded() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());
        let (url, health_lock) = &registry.workers[0];
        let mut health = health_lock.lock().unwrap();

        // Start in Unhealthy
        health.try_transition(WorkerState::Unhealthy, Duration::ZERO, url);
        assert_eq!(health.state, WorkerState::Unhealthy);

        // Probe success → Degraded
        let transitioned = health.try_transition(WorkerState::Degraded, Duration::ZERO, url);

        assert!(transitioned);
        assert_eq!(health.state, WorkerState::Degraded);
        assert!(health.unhealthy_since.is_none());
    }

    #[test]
    fn test_probe_failure_threshold_not_reached() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());
        let (_, health_lock) = &registry.workers[0];
        let mut health = health_lock.lock().unwrap();

        // Only 1 failure — below threshold of 2
        health.consecutive_probe_failures = 1;
        assert_eq!(health.state, WorkerState::Healthy);
    }

    // --- Dead declaration ---

    #[tokio::test]
    async fn test_dead_declaration_fires_after_duration() {
        let config = WorkerRegistryConfig {
            dead_declaration: Duration::from_millis(30),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&worker_urls(), config);

        // Drive to Unhealthy
        for _ in 0..4 {
            registry.record_outcome(0, true);
        }
        assert_eq!(registry.state(0), WorkerState::Unhealthy);
        assert!(!registry.is_dead(0));

        tokio::time::sleep(Duration::from_millis(40)).await;
        assert!(registry.is_dead(0));
    }

    #[test]
    fn test_healthy_worker_is_not_dead() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());
        assert!(!registry.is_dead(0));
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
        let registry = WorkerRegistry::new(&worker_urls(), config);

        // 2 errors → should cross threshold
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);
        assert_eq!(registry.state(0), WorkerState::Degraded);

        // Wait for window to expire, then add successes — error rate drops
        tokio::time::sleep(Duration::from_millis(40)).await;
        registry.record_outcome(0, false);
        registry.record_outcome(0, false);

        // The old errors are pruned; now 0/2 = 0% error rate
        let (rate, count) = {
            let (_, health_lock) = &registry.workers[0];
            let mut health = health_lock.lock().unwrap();
            health.passive_error_rate(Duration::from_millis(30))
        };

        assert_eq!(count, 2);
        assert_eq!(rate, 0.0);
    }

    // --- Multiple workers ---

    #[test]
    fn test_worker_count() {
        let registry = WorkerRegistry::new(&multi_worker_urls(), no_cooldown_config());
        assert_eq!(registry.worker_count(), 3);
    }

    #[test]
    fn test_states_are_independent_per_worker() {
        let registry = WorkerRegistry::new(&multi_worker_urls(), no_cooldown_config());

        // Drive worker 1 to Unhealthy; workers 0 and 2 are untouched
        for _ in 0..4 {
            registry.record_outcome(1, true);
        }

        assert_eq!(registry.state(0), WorkerState::Healthy);
        assert_eq!(registry.state(1), WorkerState::Unhealthy);
        assert_eq!(registry.state(2), WorkerState::Healthy);
    }

    #[test]
    fn test_workers_can_be_in_different_states() {
        let registry = WorkerRegistry::new(&multi_worker_urls(), no_cooldown_config());

        // Worker 0: Healthy (no errors)
        // Worker 1: Degraded (just crossed passive threshold)
        registry.record_outcome(1, true);
        registry.record_outcome(1, true);
        registry.record_outcome(1, true);
        // Worker 2: Unhealthy
        for _ in 0..4 {
            registry.record_outcome(2, true);
        }

        assert_eq!(registry.state(0), WorkerState::Healthy);
        assert_eq!(registry.state(1), WorkerState::Degraded);
        assert_eq!(registry.state(2), WorkerState::Unhealthy);
    }

    #[tokio::test]
    async fn test_is_dead_is_per_worker() {
        let config = WorkerRegistryConfig {
            dead_declaration: Duration::from_millis(30),
            ..no_cooldown_config()
        };
        let registry = WorkerRegistry::new(&multi_worker_urls(), config);

        // Drive only worker 2 to Unhealthy
        for _ in 0..4 {
            registry.record_outcome(2, true);
        }

        tokio::time::sleep(Duration::from_millis(40)).await;

        assert!(!registry.is_dead(0));
        assert!(!registry.is_dead(1));
        assert!(registry.is_dead(2));
    }

    #[test]
    fn test_outcome_targets_correct_worker() {
        let registry = WorkerRegistry::new(&multi_worker_urls(), no_cooldown_config());

        // Record enough errors on worker 2 to cross threshold
        registry.record_outcome(2, true);
        registry.record_outcome(2, true);
        registry.record_outcome(2, true);

        // Workers 0 and 1 must be unaffected
        assert_eq!(registry.state(0), WorkerState::Healthy);
        assert_eq!(registry.state(1), WorkerState::Healthy);
        assert_eq!(registry.state(2), WorkerState::Degraded);
    }

    // --- consecutive_probe_failures reset on transition ---

    #[test]
    fn test_probe_failure_count_reset_on_passive_transition() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());

        // One probe failure accumulates count=1.
        {
            let (_, health_lock) = &registry.workers[0];
            let mut health = health_lock.lock().unwrap();
            health.consecutive_probe_failures = 1;
        }

        // Passive signal drives Healthy → Degraded; try_transition must reset count.
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);
        registry.record_outcome(0, true);
        assert_eq!(registry.state(0), WorkerState::Degraded);

        let (_, health_lock) = &registry.workers[0];
        let health = health_lock.lock().unwrap();
        assert_eq!(
            health.consecutive_probe_failures, 0,
            "try_transition must reset consecutive_probe_failures so the Degraded epoch needs a full probe_failure_threshold failures to reach Unhealthy"
        );
    }

    // --- passive_window size cap ---

    #[test]
    fn test_passive_window_capped_at_max_entries() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());

        for _ in 0..PASSIVE_WINDOW_MAX_ENTRIES + 10 {
            registry.record_outcome(0, false);
        }

        let (_, health_lock) = &registry.workers[0];
        let health = health_lock.lock().unwrap();
        assert!(
            health.passive_window.len() <= PASSIVE_WINDOW_MAX_ENTRIES,
            "passive_window must not exceed PASSIVE_WINDOW_MAX_ENTRIES"
        );
    }

    // --- Same-state no-op ---

    #[test]
    fn test_transition_to_same_state_is_noop() {
        let registry = WorkerRegistry::new(&worker_urls(), no_cooldown_config());
        let (url, health_lock) = &registry.workers[0];
        let mut health = health_lock.lock().unwrap();

        let transitioned = health.try_transition(WorkerState::Healthy, Duration::ZERO, url);

        assert!(!transitioned);
        assert_eq!(health.state, WorkerState::Healthy);
    }
}
