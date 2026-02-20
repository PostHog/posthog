use std::time::{Duration, Instant};

use common_metrics::gauge;
use tokio::runtime::RuntimeMetrics;
use tokio::time::interval;

use crate::metrics::consts::{
    TOKIO_RUNTIME_ALIVE_TASKS, TOKIO_RUNTIME_BUSY_RATIO, TOKIO_RUNTIME_GLOBAL_QUEUE_DEPTH,
    TOKIO_RUNTIME_NUM_WORKERS, TOKIO_WORKER_BUSY_DURATION_DELTA, TOKIO_WORKER_PARK_DELTA,
};

#[cfg(tokio_unstable)]
use crate::metrics::consts::{
    TOKIO_BLOCKING_QUEUE_DEPTH, TOKIO_BLOCKING_THREADS, TOKIO_IDLE_BLOCKING_THREADS,
    TOKIO_WORKER_LOCAL_QUEUE_DEPTH, TOKIO_WORKER_MEAN_POLL_TIME_US, TOKIO_WORKER_OVERFLOW_DELTA,
    TOKIO_WORKER_POLL_DELTA, TOKIO_WORKER_STEAL_DELTA,
};

const SAMPLING_INTERVAL: Duration = Duration::from_secs(15);

pub struct TokioRuntimeMonitor {
    metrics: RuntimeMetrics,
}

impl TokioRuntimeMonitor {
    pub fn new(handle: &tokio::runtime::Handle) -> Self {
        Self {
            metrics: handle.metrics(),
        }
    }

    pub async fn start_monitoring(self) {
        let num_workers = self.metrics.num_workers();

        tracing::info!(
            "Starting Tokio runtime monitoring (workers={}, interval={}s)",
            num_workers,
            SAMPLING_INTERVAL.as_secs()
        );

        gauge(TOKIO_RUNTIME_NUM_WORKERS, &[], num_workers as f64);

        let mut stable_state = WorkerState::new(num_workers, &self.metrics);

        #[cfg(tokio_unstable)]
        {
            let mut unstable_state = UnstableWorkerState::new(num_workers, &self.metrics);
            self.run_unstable_loop(&mut stable_state, &mut unstable_state)
                .await;
        }

        #[cfg(not(tokio_unstable))]
        {
            self.run_stable_loop(&mut stable_state).await;
        }
    }

    #[cfg(not(tokio_unstable))]
    async fn run_stable_loop(&self, state: &mut WorkerState) {
        tracing::warn!(
            "tokio_unstable not enabled — blocking pool and some per-worker metrics \
             (poll count, steal count, overflow count, local queue depth, mean poll time) \
             are unavailable. Enable with rustflags = [\"--cfg\", \"tokio_unstable\"] for full metrics."
        );

        let mut ticker = interval(SAMPLING_INTERVAL);
        // Skip the immediate first tick so the first report comes after a full interval
        ticker.tick().await;

        loop {
            ticker.tick().await;

            let now = Instant::now();
            let elapsed = now.duration_since(state.last_sample);
            state.last_sample = now;

            self.report_stable_metrics(state, elapsed);
        }
    }

    #[cfg(tokio_unstable)]
    async fn run_unstable_loop(
        &self,
        stable_state: &mut WorkerState,
        unstable_state: &mut UnstableWorkerState,
    ) {
        let mut ticker = interval(SAMPLING_INTERVAL);
        // Skip the immediate first tick so the first report comes after a full interval
        ticker.tick().await;

        loop {
            ticker.tick().await;

            let now = Instant::now();
            let elapsed = now.duration_since(stable_state.last_sample);
            stable_state.last_sample = now;

            self.report_stable_metrics(stable_state, elapsed);
            self.report_unstable_metrics(unstable_state, &stable_state.worker_labels);
        }
    }

    fn report_stable_metrics(&self, state: &mut WorkerState, elapsed: Duration) {
        gauge(
            TOKIO_RUNTIME_ALIVE_TASKS,
            &[],
            self.metrics.num_alive_tasks() as f64,
        );
        gauge(
            TOKIO_RUNTIME_GLOBAL_QUEUE_DEPTH,
            &[],
            self.metrics.global_queue_depth() as f64,
        );

        let num_workers = self.metrics.num_workers();
        let elapsed_secs = elapsed.as_secs_f64();
        let mut total_busy_delta = Duration::ZERO;

        for i in 0..num_workers {
            let label = &state.worker_labels[i];

            // Busy duration (stable API)
            let busy = self.metrics.worker_total_busy_duration(i);
            let busy_delta = busy.saturating_sub(state.prev_busy[i]);
            state.prev_busy[i] = busy;
            total_busy_delta += busy_delta;

            gauge(
                TOKIO_WORKER_BUSY_DURATION_DELTA,
                label,
                busy_delta.as_secs_f64(),
            );

            // Park count (stable API)
            let parks = self.metrics.worker_park_count(i);
            let park_delta = parks.saturating_sub(state.prev_parks[i]);
            state.prev_parks[i] = parks;
            gauge(TOKIO_WORKER_PARK_DELTA, label, park_delta as f64);
        }

        let busy_ratio = if elapsed_secs > 0.0 && num_workers > 0 {
            total_busy_delta.as_secs_f64() / (elapsed_secs * num_workers as f64)
        } else {
            0.0
        };
        gauge(TOKIO_RUNTIME_BUSY_RATIO, &[], busy_ratio);
    }

    #[cfg(tokio_unstable)]
    fn report_unstable_metrics(
        &self,
        state: &mut UnstableWorkerState,
        worker_labels: &[[(String, String); 1]],
    ) {
        let num_workers = self.metrics.num_workers();

        // Blocking pool
        gauge(
            TOKIO_BLOCKING_THREADS,
            &[],
            self.metrics.num_blocking_threads() as f64,
        );
        gauge(
            TOKIO_IDLE_BLOCKING_THREADS,
            &[],
            self.metrics.num_idle_blocking_threads() as f64,
        );
        gauge(
            TOKIO_BLOCKING_QUEUE_DEPTH,
            &[],
            self.metrics.blocking_queue_depth() as f64,
        );

        for i in 0..num_workers {
            let label = &worker_labels[i];

            // Poll count
            let polls = self.metrics.worker_poll_count(i);
            let poll_delta = polls.saturating_sub(state.prev_polls[i]);
            state.prev_polls[i] = polls;
            gauge(TOKIO_WORKER_POLL_DELTA, label, poll_delta as f64);

            // Steal count
            let steals = self.metrics.worker_steal_count(i);
            let steal_delta = steals.saturating_sub(state.prev_steals[i]);
            state.prev_steals[i] = steals;
            gauge(TOKIO_WORKER_STEAL_DELTA, label, steal_delta as f64);

            // Overflow count
            let overflows = self.metrics.worker_overflow_count(i);
            let overflow_delta = overflows.saturating_sub(state.prev_overflows[i]);
            state.prev_overflows[i] = overflows;
            gauge(TOKIO_WORKER_OVERFLOW_DELTA, label, overflow_delta as f64);

            // Instantaneous gauges (not deltas)
            gauge(
                TOKIO_WORKER_LOCAL_QUEUE_DEPTH,
                label,
                self.metrics.worker_local_queue_depth(i) as f64,
            );
            gauge(
                TOKIO_WORKER_MEAN_POLL_TIME_US,
                label,
                self.metrics.worker_mean_poll_time(i).as_micros() as f64,
            );
        }
    }
}

struct WorkerState {
    last_sample: Instant,
    worker_labels: Vec<[(String, String); 1]>,
    prev_busy: Vec<Duration>,
    prev_parks: Vec<u64>,
}

impl WorkerState {
    fn new(num_workers: usize, metrics: &RuntimeMetrics) -> Self {
        let worker_labels: Vec<[(String, String); 1]> = (0..num_workers)
            .map(|i| [("worker".to_string(), i.to_string())])
            .collect();

        let mut prev_busy = vec![Duration::ZERO; num_workers];
        let mut prev_parks = vec![0u64; num_workers];

        // Snapshot current values so the first delta is accurate
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

        // Snapshot current values so the first delta is accurate
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

    #[tokio::test]
    async fn spawned_task_increases_alive_count() {
        let handle = tokio::runtime::Handle::current();
        let before = handle.metrics().num_alive_tasks();

        // Hold a task alive — single-threaded runtime won't poll it until we yield
        let (tx, rx) = tokio::sync::oneshot::channel::<()>();
        let task = tokio::spawn(async move {
            rx.await.ok();
        });

        let after = handle.metrics().num_alive_tasks();
        assert!(
            after > before,
            "alive tasks should increase after spawn: before={before}, after={after}"
        );

        let monitor = TokioRuntimeMonitor::new(&handle);
        let num_workers = handle.metrics().num_workers();
        let mut state = WorkerState::new(num_workers, &handle.metrics());
        monitor.report_stable_metrics(&mut state, Duration::from_secs(15));

        tx.send(()).ok();
        task.await.ok();
    }

    #[cfg(tokio_unstable)]
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn poll_and_busy_deltas_advance_after_work() {
        let handle = tokio::runtime::Handle::current();
        let metrics = handle.metrics();
        let num_workers = metrics.num_workers();
        let monitor = TokioRuntimeMonitor::new(&handle);

        let mut stable_state = WorkerState::new(num_workers, &metrics);
        let mut unstable_state = UnstableWorkerState::new(num_workers, &metrics);
        let polls_before: Vec<u64> = unstable_state.prev_polls.clone();
        let busy_before: Vec<Duration> = stable_state.prev_busy.clone();

        // Spawn real tasks so worker threads register polls
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
        assert!(
            polls_advanced,
            "poll counts should advance: before={polls_before:?}, after={:?}",
            unstable_state.prev_polls
        );

        let busy_advanced = stable_state
            .prev_busy
            .iter()
            .zip(busy_before.iter())
            .any(|(after, before)| after > before);
        assert!(
            busy_advanced,
            "busy durations should advance: before={busy_before:?}, after={:?}",
            stable_state.prev_busy
        );
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn busy_ratio_bounded_with_real_elapsed() {
        let handle = tokio::runtime::Handle::current();
        let metrics = handle.metrics();
        let num_workers = metrics.num_workers();

        let busy_before: Vec<Duration> = (0..num_workers)
            .map(|i| metrics.worker_total_busy_duration(i))
            .collect();

        let start = std::time::Instant::now();
        for _ in 0..1000 {
            tokio::task::yield_now().await;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
        let elapsed = start.elapsed();

        let mut total_busy_delta = Duration::ZERO;
        for i in 0..num_workers {
            let busy_now = metrics.worker_total_busy_duration(i);
            total_busy_delta += busy_now.saturating_sub(busy_before[i]);
        }

        let ratio = total_busy_delta.as_secs_f64() / (elapsed.as_secs_f64() * num_workers as f64);
        assert!(
            (0.0..=1.0).contains(&ratio),
            "busy ratio should be in [0, 1], got {ratio}"
        );
    }
}
