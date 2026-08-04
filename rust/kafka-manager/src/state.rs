//! In-memory fleet state: the last reports per pod, TTL eviction, and the
//! derived per-deployment aggregates exported as Prometheus gauges.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use kafka_manager_types::{DeliveryCounts, HealthReport};
use metrics::{counter, gauge};
use serde::Serialize;

pub struct FleetState {
    ttl: Duration,
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    pods: HashMap<PodKey, PodEntry>,
    /// Deployments ever seen this process lifetime. Gauges are re-emitted for
    /// all of them on every sweep, so a deployment going fully silent reads
    /// as `pods_reporting == 0` instead of a frozen last value.
    deployments: BTreeSet<String>,
}

type PodKey = (String, String);

struct PodEntry {
    report: HealthReport,
    received_at: Instant,
    /// The previous report's arrival time and cumulative counts, kept so
    /// interval rates survive between sweeps.
    prev: Option<(Instant, DeliveryCounts)>,
}

/// Interval rates derived from two consecutive cumulative reports.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct IntervalRates {
    /// Failures over attempts with a known outcome in the interval. `None`
    /// when the interval saw no attempts.
    pub failure_ratio: Option<f64>,
    pub acks_per_second: f64,
}

#[derive(Serialize)]
pub struct FleetSnapshot {
    pub deployments: Vec<DeploymentSnapshot>,
}

#[derive(Serialize)]
pub struct DeploymentSnapshot {
    pub deployment: String,
    pub pods: Vec<PodSnapshot>,
}

#[derive(Serialize)]
pub struct PodSnapshot {
    pub pod: String,
    pub seconds_since_report: u64,
    pub queue_fill_ratio: Option<f64>,
    pub brokers_down: Option<u32>,
    pub interval: Option<IntervalRates>,
    pub delivery: DeliveryCounts,
}

impl FleetState {
    pub fn new(ttl: Duration) -> Self {
        Self {
            ttl,
            inner: Mutex::new(Inner::default()),
        }
    }

    pub fn ingest(&self, report: HealthReport) {
        self.ingest_at(report, Instant::now());
    }

    pub fn ingest_at(&self, report: HealthReport, now: Instant) {
        let mut inner = self.inner.lock().unwrap();
        inner.deployments.insert(report.deployment.clone());
        let key = (report.deployment.clone(), report.pod.clone());
        match inner.pods.entry(key) {
            std::collections::hash_map::Entry::Occupied(mut occupied) => {
                let entry = occupied.get_mut();
                entry.prev = Some((entry.received_at, entry.report.delivery));
                entry.report = report;
                entry.received_at = now;
            }
            std::collections::hash_map::Entry::Vacant(vacant) => {
                vacant.insert(PodEntry {
                    report,
                    received_at: now,
                    prev: None,
                });
            }
        }
    }

    /// Evict pods past the TTL and re-emit the per-deployment gauges.
    pub fn sweep(&self) {
        self.sweep_at(Instant::now());
    }

    pub fn sweep_at(&self, now: Instant) {
        let mut inner = self.inner.lock().unwrap();
        let ttl = self.ttl;
        inner.pods.retain(|(deployment, _), entry| {
            let alive = now.duration_since(entry.received_at) <= ttl;
            if !alive {
                let deployment: Arc<str> = Arc::from(deployment.as_str());
                counter!("kafka_manager_pods_expired_total", "deployment" => deployment)
                    .increment(1);
            }
            alive
        });

        let mut per_deployment: BTreeMap<&str, DeploymentAggregates> = inner
            .deployments
            .iter()
            .map(|d| (d.as_str(), DeploymentAggregates::default()))
            .collect();
        for ((deployment, _), entry) in &inner.pods {
            let aggregates = per_deployment
                .get_mut(deployment.as_str())
                .expect("pod deployment missing from seen-deployment set");
            aggregates.observe(entry);
        }

        for (deployment, aggregates) in per_deployment {
            let deployment: Arc<str> = Arc::from(deployment);
            gauge!("kafka_manager_pods_reporting", "deployment" => deployment.clone())
                .set(aggregates.pods as f64);
            gauge!("kafka_manager_queue_fill_ratio_max", "deployment" => deployment.clone())
                .set(aggregates.queue_fill_ratio_max);
            gauge!("kafka_manager_brokers_down_max", "deployment" => deployment.clone())
                .set(aggregates.brokers_down_max as f64);
            gauge!("kafka_manager_delivery_failure_ratio_max", "deployment" => deployment.clone())
                .set(aggregates.failure_ratio_max);
            gauge!("kafka_manager_delivery_acks_per_second", "deployment" => deployment)
                .set(aggregates.acks_per_second);
        }
    }

    pub fn snapshot(&self) -> FleetSnapshot {
        self.snapshot_at(Instant::now())
    }

    pub fn snapshot_at(&self, now: Instant) -> FleetSnapshot {
        let inner = self.inner.lock().unwrap();
        let mut deployments: BTreeMap<&str, Vec<PodSnapshot>> = BTreeMap::new();
        for ((deployment, pod), entry) in &inner.pods {
            deployments
                .entry(deployment.as_str())
                .or_default()
                .push(PodSnapshot {
                    pod: pod.clone(),
                    seconds_since_report: now.duration_since(entry.received_at).as_secs(),
                    queue_fill_ratio: entry.queue_fill_ratio(),
                    brokers_down: entry
                        .report
                        .producer
                        .as_ref()
                        .map(|p| p.brokers_total.saturating_sub(p.brokers_up)),
                    interval: entry.interval_rates(),
                    delivery: entry.report.delivery,
                });
        }
        FleetSnapshot {
            deployments: deployments
                .into_iter()
                .map(|(deployment, mut pods)| {
                    pods.sort_by(|a, b| a.pod.cmp(&b.pod));
                    DeploymentSnapshot {
                        deployment: deployment.to_string(),
                        pods,
                    }
                })
                .collect(),
        }
    }
}

#[derive(Default)]
struct DeploymentAggregates {
    pods: usize,
    queue_fill_ratio_max: f64,
    brokers_down_max: u32,
    failure_ratio_max: f64,
    acks_per_second: f64,
}

impl DeploymentAggregates {
    fn observe(&mut self, entry: &PodEntry) {
        self.pods += 1;
        if let Some(ratio) = entry.queue_fill_ratio() {
            self.queue_fill_ratio_max = self.queue_fill_ratio_max.max(ratio);
        }
        if let Some(producer) = &entry.report.producer {
            self.brokers_down_max = self
                .brokers_down_max
                .max(producer.brokers_total.saturating_sub(producer.brokers_up));
        }
        if let Some(rates) = entry.interval_rates() {
            if let Some(ratio) = rates.failure_ratio {
                self.failure_ratio_max = self.failure_ratio_max.max(ratio);
            }
            self.acks_per_second += rates.acks_per_second;
        }
    }
}

impl PodEntry {
    fn queue_fill_ratio(&self) -> Option<f64> {
        let producer = self.report.producer.as_ref()?;
        if producer.queue_capacity == 0 {
            return None;
        }
        Some(producer.queue_depth as f64 / producer.queue_capacity as f64)
    }

    /// Rates over the last inter-report interval. `None` until two reports
    /// have arrived, or when the counters went backwards (process restart —
    /// the next interval will be clean).
    fn interval_rates(&self) -> Option<IntervalRates> {
        let (prev_at, prev) = self.prev.as_ref()?;
        let current = &self.report.delivery;
        if current.total() < prev.total() || current.failures() < prev.failures() {
            return None;
        }
        let elapsed = self.received_at.duration_since(*prev_at).as_secs_f64();
        if elapsed <= 0.0 {
            return None;
        }
        let attempts = current.total() - prev.total();
        let failures = current.failures() - prev.failures();
        Some(IntervalRates {
            failure_ratio: (attempts > 0).then(|| failures as f64 / attempts as f64),
            acks_per_second: attempts as f64 / elapsed,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use kafka_manager_types::ProducerStats;

    fn report(pod: &str, ok: u64, broker_error: u64) -> HealthReport {
        HealthReport {
            pod: pod.to_string(),
            deployment: "capture".to_string(),
            delivery: DeliveryCounts {
                ok,
                broker_error,
                ..Default::default()
            },
            producer: Some(ProducerStats {
                queue_depth: 100,
                queue_capacity: 1000,
                brokers_up: 3,
                brokers_total: 3,
                brokers: vec![],
            }),
        }
    }

    #[test]
    fn interval_rates_need_two_reports() {
        let state = FleetState::new(Duration::from_secs(60));
        let t0 = Instant::now();
        state.ingest_at(report("pod-a", 100, 0), t0);
        let snapshot = state.snapshot_at(t0);
        assert!(snapshot.deployments[0].pods[0].interval.is_none());

        state.ingest_at(report("pod-a", 190, 10), t0 + Duration::from_secs(10));
        let snapshot = state.snapshot_at(t0 + Duration::from_secs(10));
        let rates = snapshot.deployments[0].pods[0].interval.unwrap();
        assert_eq!(rates.failure_ratio, Some(0.1));
        assert_eq!(rates.acks_per_second, 10.0);
    }

    #[test]
    fn counter_reset_suppresses_rates_for_one_interval() {
        let state = FleetState::new(Duration::from_secs(60));
        let t0 = Instant::now();
        state.ingest_at(report("pod-a", 1000, 5), t0);
        // Pod restarted: cumulative counters start over below previous values.
        state.ingest_at(report("pod-a", 50, 0), t0 + Duration::from_secs(10));
        let snapshot = state.snapshot_at(t0 + Duration::from_secs(10));
        assert!(snapshot.deployments[0].pods[0].interval.is_none());

        state.ingest_at(report("pod-a", 150, 0), t0 + Duration::from_secs(20));
        let snapshot = state.snapshot_at(t0 + Duration::from_secs(20));
        assert!(snapshot.deployments[0].pods[0].interval.is_some());
    }

    #[test]
    fn sweep_evicts_stale_pods() {
        let state = FleetState::new(Duration::from_secs(60));
        let t0 = Instant::now();
        state.ingest_at(report("pod-a", 1, 0), t0);
        state.ingest_at(report("pod-b", 1, 0), t0 + Duration::from_secs(50));

        state.sweep_at(t0 + Duration::from_secs(70));
        let snapshot = state.snapshot_at(t0 + Duration::from_secs(70));
        let pods: Vec<_> = snapshot.deployments[0]
            .pods
            .iter()
            .map(|p| p.pod.as_str())
            .collect();
        assert_eq!(pods, vec!["pod-b"]);
    }

    #[test]
    fn queue_fill_ratio_from_latest_stats() {
        let state = FleetState::new(Duration::from_secs(60));
        state.ingest(report("pod-a", 1, 0));
        let snapshot = state.snapshot();
        assert_eq!(snapshot.deployments[0].pods[0].queue_fill_ratio, Some(0.1));
    }
}
