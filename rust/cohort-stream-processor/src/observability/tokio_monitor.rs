//! Periodic Tokio runtime monitor: per-worker busy-ratio, queue depths, and blocking-pool depth.
//! Full per-worker and blocking-pool metrics require `tokio_unstable` (enabled workspace-wide).

use std::sync::Arc;
use std::time::{Duration, Instant};

use lifecycle::Handle;
use metrics::gauge;
use tokio::runtime::RuntimeMetrics;
use tokio::time::interval;

use crate::observability::metrics::{
    TOKIO_RUNTIME_ALIVE_TASKS, TOKIO_RUNTIME_BUSY_RATIO, TOKIO_RUNTIME_GLOBAL_QUEUE_DEPTH,
    TOKIO_RUNTIME_NUM_WORKERS, TOKIO_WORKER_BUSY_DURATION_DELTA, TOKIO_WORKER_PARK_DELTA,
};

#[cfg(tokio_unstable)]
use crate::observability::metrics::{
    TOKIO_BLOCKING_QUEUE_DEPTH, TOKIO_BLOCKING_THREADS, TOKIO_IDLE_BLOCKING_THREADS,
    TOKIO_WORKER_LOCAL_QUEUE_DEPTH, TOKIO_WORKER_MEAN_POLL_TIME_US, TOKIO_WORKER_OVERFLOW_DELTA,
    TOKIO_WORKER_POLL_DELTA, TOKIO_WORKER_STEAL_DELTA,
};

/// Samples [`RuntimeMetrics`] on a fixed cadence and publishes worker-utilization gauges. Per-worker
/// counters are published as deltas over the interval.
pub struct TokioRuntimeMonitor {
    metrics: RuntimeMetrics,
    interval: Duration,
}

impl TokioRuntimeMonitor {
    pub fn new(handle: &tokio::runtime::Handle, interval: Duration) -> Self {
        Self {
            metrics: handle.metrics(),
            interval,
        }
    }

    pub async fn start_monitoring(self, shutdown: Handle) {
        let _scope = shutdown.process_scope();
        let num_workers = self.metrics.num_workers();

        tracing::info!(
            workers = num_workers,
            interval_secs = self.interval.as_secs(),
            "starting Tokio runtime monitor",
        );

        gauge!(TOKIO_RUNTIME_NUM_WORKERS).set(num_workers as f64);

        let mut stable_state = WorkerState::new(num_workers, &self.metrics);

        #[cfg(tokio_unstable)]
        let mut unstable_state = UnstableWorkerState::new(num_workers, &self.metrics);

        self.run_loop(
            &shutdown,
            &mut stable_state,
            #[cfg(tokio_unstable)]
            &mut unstable_state,
        )
        .await;
    }

    async fn run_loop(
        &self,
        shutdown: &Handle,
        stable_state: &mut WorkerState,
        #[cfg(tokio_unstable)] unstable_state: &mut UnstableWorkerState,
    ) {
        #[cfg(not(tokio_unstable))]
        tracing::warn!(
            "tokio_unstable not enabled — blocking pool and some per-worker metrics \
             (poll count, steal count, overflow count, local queue depth, mean poll time) \
             are unavailable. Enable with rustflags = [\"--cfg\", \"tokio_unstable\"] for full metrics."
        );

        let mut ticker = interval(self.interval);
        // Skip the immediate first tick so the first report reflects a full interval of deltas.
        ticker.tick().await;

        loop {
            tokio::select! {
                _ = shutdown.shutdown_recv() => {
                    tracing::info!("Tokio runtime monitor shutting down");
                    break;
                }
                _ = ticker.tick() => {
                    let now = Instant::now();
                    let elapsed = now.duration_since(stable_state.last_sample);
                    stable_state.last_sample = now;

                    self.report_stable_metrics(stable_state, elapsed);

                    #[cfg(tokio_unstable)]
                    self.report_unstable_metrics(unstable_state, &stable_state.worker_labels);
                }
            }
        }
    }

    fn report_stable_metrics(&self, state: &mut WorkerState, elapsed: Duration) {
        gauge!(TOKIO_RUNTIME_ALIVE_TASKS).set(self.metrics.num_alive_tasks() as f64);
        gauge!(TOKIO_RUNTIME_GLOBAL_QUEUE_DEPTH).set(self.metrics.global_queue_depth() as f64);

        let num_workers = self.metrics.num_workers();
        let elapsed_secs = elapsed.as_secs_f64();
        let mut total_busy_delta = Duration::ZERO;

        // busy-duration and park-count are tokio's only stable per-worker metrics; the rest are
        // gathered under `tokio_unstable` in `report_unstable_metrics`.
        for i in 0..num_workers {
            let label = state.worker_labels[i].clone();

            let busy = self.metrics.worker_total_busy_duration(i);
            let busy_delta = busy.saturating_sub(state.prev_busy[i]);
            state.prev_busy[i] = busy;
            total_busy_delta += busy_delta;
            gauge!(TOKIO_WORKER_BUSY_DURATION_DELTA, "worker" => label.clone())
                .set(busy_delta.as_secs_f64());

            let parks = self.metrics.worker_park_count(i);
            let park_delta = parks.saturating_sub(state.prev_parks[i]);
            state.prev_parks[i] = parks;
            gauge!(TOKIO_WORKER_PARK_DELTA, "worker" => label).set(park_delta as f64);
        }

        let busy_ratio = if elapsed_secs > 0.0 && num_workers > 0 {
            total_busy_delta.as_secs_f64() / (elapsed_secs * num_workers as f64)
        } else {
            0.0
        };
        gauge!(TOKIO_RUNTIME_BUSY_RATIO).set(busy_ratio);
    }

    #[cfg(tokio_unstable)]
    fn report_unstable_metrics(&self, state: &mut UnstableWorkerState, worker_labels: &[Arc<str>]) {
        let num_workers = self.metrics.num_workers();

        gauge!(TOKIO_BLOCKING_THREADS).set(self.metrics.num_blocking_threads() as f64);
        gauge!(TOKIO_IDLE_BLOCKING_THREADS).set(self.metrics.num_idle_blocking_threads() as f64);
        gauge!(TOKIO_BLOCKING_QUEUE_DEPTH).set(self.metrics.blocking_queue_depth() as f64);

        for (i, label) in worker_labels.iter().enumerate().take(num_workers) {
            let polls = self.metrics.worker_poll_count(i);
            let poll_delta = polls.saturating_sub(state.prev_polls[i]);
            state.prev_polls[i] = polls;
            gauge!(TOKIO_WORKER_POLL_DELTA, "worker" => label.clone()).set(poll_delta as f64);

            let steals = self.metrics.worker_steal_count(i);
            let steal_delta = steals.saturating_sub(state.prev_steals[i]);
            state.prev_steals[i] = steals;
            gauge!(TOKIO_WORKER_STEAL_DELTA, "worker" => label.clone()).set(steal_delta as f64);

            let overflows = self.metrics.worker_overflow_count(i);
            let overflow_delta = overflows.saturating_sub(state.prev_overflows[i]);
            state.prev_overflows[i] = overflows;
            gauge!(TOKIO_WORKER_OVERFLOW_DELTA, "worker" => label.clone())
                .set(overflow_delta as f64);

            // Instantaneous gauges, not deltas.
            gauge!(TOKIO_WORKER_LOCAL_QUEUE_DEPTH, "worker" => label.clone())
                .set(self.metrics.worker_local_queue_depth(i) as f64);
            gauge!(TOKIO_WORKER_MEAN_POLL_TIME_US, "worker" => label.clone())
                .set(self.metrics.worker_mean_poll_time(i).as_micros() as f64);
        }
    }
}

struct WorkerState {
    last_sample: Instant,
    /// Per-worker `worker` label, built once and cloned into each macro call.
    worker_labels: Vec<Arc<str>>,
    prev_busy: Vec<Duration>,
    prev_parks: Vec<u64>,
}

impl WorkerState {
    fn new(num_workers: usize, metrics: &RuntimeMetrics) -> Self {
        let worker_labels: Vec<Arc<str>> =
            (0..num_workers).map(|i| Arc::from(i.to_string())).collect();

        let mut prev_busy = vec![Duration::ZERO; num_workers];
        let mut prev_parks = vec![0u64; num_workers];

        // Snapshot current values so the first delta is accurate.
        for i in 0..num_workers {
            prev_busy[i] = metrics.worker_total_busy_duration(i);
            prev_parks[i] = metrics.worker_park_count(i);
        }

        Self {
            last_sample: Instant::now(),
            worker_labels,
            prev_busy,
            prev_parks,
        }
    }
}

#[cfg(tokio_unstable)]
struct UnstableWorkerState {
    prev_polls: Vec<u64>,
    prev_steals: Vec<u64>,
    prev_overflows: Vec<u64>,
}

#[cfg(tokio_unstable)]
impl UnstableWorkerState {
    fn new(num_workers: usize, metrics: &RuntimeMetrics) -> Self {
        let mut prev_polls = vec![0u64; num_workers];
        let mut prev_steals = vec![0u64; num_workers];
        let mut prev_overflows = vec![0u64; num_workers];

        // Snapshot current values so the first delta is accurate.
        for i in 0..num_workers {
            prev_polls[i] = metrics.worker_poll_count(i);
            prev_steals[i] = metrics.worker_steal_count(i);
            prev_overflows[i] = metrics.worker_overflow_count(i);
        }

        Self {
            prev_polls,
            prev_steals,
            prev_overflows,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Runs the emission path and checks the busy-ratio stays in [0, 1] over a real elapsed window.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn busy_ratio_bounded_with_real_elapsed() {
        let handle = tokio::runtime::Handle::current();
        let metrics = handle.metrics();
        let num_workers = metrics.num_workers();
        let monitor = TokioRuntimeMonitor::new(&handle, Duration::from_secs(15));
        let mut state = WorkerState::new(num_workers, &metrics);

        let busy_before: Vec<Duration> = (0..num_workers)
            .map(|i| metrics.worker_total_busy_duration(i))
            .collect();

        let start = Instant::now();
        for _ in 0..1000 {
            tokio::task::yield_now().await;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
        let elapsed = start.elapsed();

        monitor.report_stable_metrics(&mut state, elapsed);

        let mut total_busy_delta = Duration::ZERO;
        for (i, &before) in busy_before.iter().enumerate().take(num_workers) {
            let busy_now = metrics.worker_total_busy_duration(i);
            total_busy_delta += busy_now.saturating_sub(before);
        }

        let ratio = total_busy_delta.as_secs_f64() / (elapsed.as_secs_f64() * num_workers as f64);
        assert!(
            (0.0..=1.0).contains(&ratio),
            "busy ratio should be in [0, 1], got {ratio}"
        );
    }

    // Covers the unstable delta path (poll/steal/overflow), which runs in production because
    // `tokio_unstable` is enabled workspace-wide: a wrong `saturating_sub` order or a missed
    // `prev_*` update would emit silently wrong deltas that the stable-path test cannot catch.
    #[cfg(tokio_unstable)]
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn poll_and_busy_deltas_advance_after_work() {
        let handle = tokio::runtime::Handle::current();
        let metrics = handle.metrics();
        let num_workers = metrics.num_workers();
        let monitor = TokioRuntimeMonitor::new(&handle, Duration::from_secs(15));

        let mut stable_state = WorkerState::new(num_workers, &metrics);
        let mut unstable_state = UnstableWorkerState::new(num_workers, &metrics);
        let polls_before: Vec<u64> = unstable_state.prev_polls.clone();
        let busy_before: Vec<Duration> = stable_state.prev_busy.clone();

        let mut handles = Vec::new();
        for _ in 0..50 {
            handles.push(tokio::spawn(async {
                tokio::task::yield_now().await;
            }));
        }
        for h in handles {
            h.await.ok();
        }

        monitor.report_stable_metrics(&mut stable_state, Duration::from_secs(15));
        monitor.report_unstable_metrics(&mut unstable_state, &stable_state.worker_labels);

        let polls_advanced = unstable_state
            .prev_polls
            .iter()
            .zip(polls_before.iter())
            .any(|(after, before)| after > before);
        assert!(polls_advanced, "poll counts should advance after work");

        let busy_advanced = stable_state
            .prev_busy
            .iter()
            .zip(busy_before.iter())
            .any(|(after, before)| after > before);
        assert!(busy_advanced, "busy durations should advance after work");
    }
}
