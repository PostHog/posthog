use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use hdrhistogram::Histogram;

pub struct LatencyRecorder {
    histogram: Mutex<Histogram<u64>>,
    successes: AtomicU64,
    failures: AtomicU64,
    /// Writes refused because a lifecycle op fenced or destroyed the
    /// person. Counted apart from failures, because a merge run expects
    /// them.
    lifecycle_rejections: AtomicU64,
    start_time: Instant,
}

impl LatencyRecorder {
    pub fn new() -> Self {
        Self {
            histogram: Mutex::new(Histogram::new_with_max(60_000_000, 3).unwrap()),
            successes: AtomicU64::new(0),
            failures: AtomicU64::new(0),
            lifecycle_rejections: AtomicU64::new(0),
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

    pub fn record_lifecycle_rejection(&self) {
        self.lifecycle_rejections.fetch_add(1, Ordering::Relaxed);
    }

    pub fn snapshot(&self) -> StatsSnapshot {
        let h = self.histogram.lock().unwrap();
        let successes = self.successes.load(Ordering::Relaxed);
        let failures = self.failures.load(Ordering::Relaxed);
        let lifecycle_rejections = self.lifecycle_rejections.load(Ordering::Relaxed);
        let total = successes + failures + lifecycle_rejections;
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
            lifecycle_rejections,
            p50_us: h.value_at_quantile(0.50),
            p95_us: h.value_at_quantile(0.95),
            p99_us: h.value_at_quantile(0.99),
            elapsed,
            throughput_rps,
        }
    }
}

pub struct StatsSnapshot {
    pub total: u64,
    pub successes: u64,
    pub failures: u64,
    pub lifecycle_rejections: u64,
    pub p50_us: u64,
    pub p95_us: u64,
    pub p99_us: u64,
    pub elapsed: Duration,
    pub throughput_rps: f64,
}

pub struct StatsCollector {
    pub writes: LatencyRecorder,
    pub reads: LatencyRecorder,
    /// MergePersons calls. One call is one saga, so its latency is the
    /// full merge cost.
    pub merges: LatencyRecorder,
    /// Merge calls that involve a wide person. Kept apart so their cost
    /// does not hide in the median.
    pub wide_merges: LatencyRecorder,
    /// Merge outcomes per source, by name.
    merge_outcomes: Mutex<BTreeMap<&'static str, u64>>,
}

impl StatsCollector {
    pub fn new() -> Self {
        Self {
            writes: LatencyRecorder::new(),
            reads: LatencyRecorder::new(),
            merges: LatencyRecorder::new(),
            wide_merges: LatencyRecorder::new(),
            merge_outcomes: Mutex::new(BTreeMap::new()),
        }
    }

    pub fn record_merge_outcome(&self, outcome: &'static str) {
        if let Ok(mut outcomes) = self.merge_outcomes.lock() {
            *outcomes.entry(outcome).or_default() += 1;
        }
    }

    pub fn merge_outcomes(&self) -> BTreeMap<&'static str, u64> {
        self.merge_outcomes
            .lock()
            .map(|outcomes| outcomes.clone())
            .unwrap_or_default()
    }
}
