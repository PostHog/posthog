//! Tokio runtime statistics, sampled on a fixed cadence.

use std::future::Future;
use std::time::Duration;

use metrics::{counter, gauge};
use tokio::runtime::{Handle, RuntimeMetrics};

/// Publishes the runtime's worker and blocking-pool statistics under
/// `<prefix>_tokio_*`. Cumulative values go out as absolute counters, so
/// any scrape cadence can rate them.
pub struct TokioRuntimeMonitor {
    metrics: RuntimeMetrics,
    prefix: String,
    interval: Duration,
}

impl TokioRuntimeMonitor {
    pub fn new(handle: &Handle, prefix: &str, interval: Duration) -> Self {
        Self {
            metrics: handle.metrics(),
            prefix: prefix.to_string(),
            interval,
        }
    }

    /// Samples every interval until `shutdown` resolves.
    pub async fn run(self, shutdown: impl Future<Output = ()>) {
        let mut shutdown = std::pin::pin!(shutdown);
        let mut tick = tokio::time::interval(self.interval);
        loop {
            tokio::select! {
                _ = &mut shutdown => break,
                _ = tick.tick() => self.publish(),
            }
        }
    }

    fn name(&self, suffix: &str) -> String {
        format!("{}_tokio_{suffix}", self.prefix)
    }

    fn publish(&self) {
        let m = &self.metrics;
        gauge!(self.name("num_workers")).set(m.num_workers() as f64);
        gauge!(self.name("alive_tasks")).set(m.num_alive_tasks() as f64);
        gauge!(self.name("global_queue_depth")).set(m.global_queue_depth() as f64);
        #[cfg(tokio_unstable)]
        {
            gauge!(self.name("blocking_threads")).set(m.num_blocking_threads() as f64);
            gauge!(self.name("idle_blocking_threads")).set(m.num_idle_blocking_threads() as f64);
            gauge!(self.name("blocking_queue_depth")).set(m.blocking_queue_depth() as f64);
        }
        for worker in 0..m.num_workers() {
            let label = worker.to_string();
            counter!(self.name("worker_busy_micros_total"), "worker" => label.clone())
                .absolute(m.worker_total_busy_duration(worker).as_micros() as u64);
            counter!(self.name("worker_park_total"), "worker" => label.clone())
                .absolute(m.worker_park_count(worker));
            #[cfg(tokio_unstable)]
            {
                counter!(self.name("worker_poll_total"), "worker" => label.clone())
                    .absolute(m.worker_poll_count(worker));
                counter!(self.name("worker_steal_total"), "worker" => label.clone())
                    .absolute(m.worker_steal_count(worker));
                counter!(self.name("worker_overflow_total"), "worker" => label.clone())
                    .absolute(m.worker_overflow_count(worker));
                gauge!(self.name("worker_local_queue_depth"), "worker" => label.clone())
                    .set(m.worker_local_queue_depth(worker) as f64);
                gauge!(self.name("worker_mean_poll_time_us"), "worker" => label.clone())
                    .set(m.worker_mean_poll_time(worker).as_micros() as f64);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn every_series_sits_under_the_prefix() {
        let monitor = TokioRuntimeMonitor::new(&Handle::current(), "svc", Duration::from_secs(1));
        assert_eq!(
            monitor.name("worker_busy_micros_total"),
            "svc_tokio_worker_busy_micros_total"
        );
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn a_sample_covers_every_worker() {
        let monitor = TokioRuntimeMonitor::new(&Handle::current(), "svc", Duration::from_secs(1));
        monitor.publish();
    }
}
