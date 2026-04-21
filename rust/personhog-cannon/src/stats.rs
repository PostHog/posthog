use hdrhistogram::Histogram;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub struct LatencyRecorder {
    histogram: Mutex<Histogram<u64>>,
    successes: AtomicU64,
    failures: AtomicU64,
    start_time: Instant,
}

impl LatencyRecorder {
    pub fn new() -> Self {
        Self {
            histogram: Mutex::new(Histogram::new_with_max(60_000_000, 3).unwrap()),
            successes: AtomicU64::new(0),
            failures: AtomicU64::new(0),
            start_time: Instant::now(),
        }
    }

    pub fn record_success(&self, latency: Duration) {
        let us = latency.as_micros() as u64;
        if let Ok(mut h) = self.histogram.lock() {
            let _ = h.record(us.min(60_000_000));
        }
        self.successes.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_failure(&self) {
        self.failures.fetch_add(1, Ordering::Relaxed);
    }

    pub fn snapshot(&self) -> StatsSnapshot {
        let h = self.histogram.lock().unwrap();
        let successes = self.successes.load(Ordering::Relaxed);
        let failures = self.failures.load(Ordering::Relaxed);
        let total = successes + failures;
        let elapsed = self.start_time.elapsed();
        let throughput_rps = if elapsed.as_secs_f64() > 0.0 {
            total as f64 / elapsed.as_secs_f64()
        } else {
            0.0
        };

        StatsSnapshot {
            total,
            successes,
            failures,
            p50_us: h.value_at_quantile(0.50),
            p95_us: h.value_at_quantile(0.95),
            p99_us: h.value_at_quantile(0.99),
            p999_us: h.value_at_quantile(0.999),
            max_us: h.max(),
            mean_us: h.mean(),
            elapsed,
            throughput_rps,
        }
    }
}

#[allow(dead_code)]
pub struct StatsSnapshot {
    pub total: u64,
    pub successes: u64,
    pub failures: u64,
    pub p50_us: u64,
    pub p95_us: u64,
    pub p99_us: u64,
    pub p999_us: u64,
    pub max_us: u64,
    pub mean_us: f64,
    pub elapsed: Duration,
    pub throughput_rps: f64,
}

pub struct StatsCollector {
    pub writes: LatencyRecorder,
    pub reads: LatencyRecorder,
}

impl StatsCollector {
    pub fn new() -> Self {
        Self {
            writes: LatencyRecorder::new(),
            reads: LatencyRecorder::new(),
        }
    }
}
