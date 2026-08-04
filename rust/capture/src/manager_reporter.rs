//! Fail-open telemetry reporter to the kafka-manager service.
//!
//! Pushes periodic [`HealthReport`]s (delivery outcome counts, producer queue
//! pressure, broker connectivity) to an external kafka-manager, which
//! aggregates them fleet-wide as groundwork for a Kafka circuit breaker. The
//! channel is strictly one-way: nothing the manager does — including being
//! down — can influence the produce path.
//!
//! Fail-open by construction:
//! - Without [`init`] (the `CAPTURE_KAFKA_MANAGER_URL` env var unset), the
//!   record hooks are no-ops behind a single atomic load and no task runs.
//! - When enabled, the produce path only bumps relaxed atomics; serialization
//!   and HTTP happen on a background task with a short request timeout.
//! - Send failures increment a counter and are otherwise dropped.
//!
//! Scope: the v0 sink path. Delivery counts cover every producer built on
//! `sinks::producer`, so on deployments with a secondary sink the counts are
//! a pod-wide blend; producer stats come only from the liveness-gating
//! (primary) producer. Per-sink attribution and the v1 sink stack are next
//! steps once per-cluster breakers need them.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use kafka_manager_types::{DeliveryCounts, HealthReport, ProducerStats};
use metrics::counter;
use tracing::log::{debug, warn};

static COLLECTOR: OnceLock<Arc<Collector>> = OnceLock::new();

/// Terminal outcome of one produce attempt, as classified by the delivery
/// report handling in `sinks::producer`.
#[derive(Debug, Clone, Copy)]
pub enum DeliveryOutcome {
    Delivered,
    BrokerError,
    TimedOut,
    TooLarge,
    Abandoned,
    EnqueueError,
}

#[derive(Default)]
pub struct Collector {
    ok: AtomicU64,
    broker_error: AtomicU64,
    timed_out: AtomicU64,
    too_large: AtomicU64,
    abandoned: AtomicU64,
    enqueue_error: AtomicU64,
    producer_stats: Mutex<Option<ProducerStats>>,
}

impl Collector {
    fn record(&self, outcome: DeliveryOutcome) {
        let cell = match outcome {
            DeliveryOutcome::Delivered => &self.ok,
            DeliveryOutcome::BrokerError => &self.broker_error,
            DeliveryOutcome::TimedOut => &self.timed_out,
            DeliveryOutcome::TooLarge => &self.too_large,
            DeliveryOutcome::Abandoned => &self.abandoned,
            DeliveryOutcome::EnqueueError => &self.enqueue_error,
        };
        cell.fetch_add(1, Ordering::Relaxed);
    }

    fn delivery_counts(&self) -> DeliveryCounts {
        DeliveryCounts {
            ok: self.ok.load(Ordering::Relaxed),
            broker_error: self.broker_error.load(Ordering::Relaxed),
            timed_out: self.timed_out.load(Ordering::Relaxed),
            too_large: self.too_large.load(Ordering::Relaxed),
            abandoned: self.abandoned.load(Ordering::Relaxed),
            enqueue_error: self.enqueue_error.load(Ordering::Relaxed),
        }
    }
}

/// Whether a reporter is installed. Callers use this to skip assembling
/// snapshots that would go nowhere (the stats callback builds a per-broker
/// Vec only when this is true).
pub fn enabled() -> bool {
    COLLECTOR.get().is_some()
}

/// No-op unless [`init`] ran: one atomic load, then one relaxed increment.
pub fn record_delivery_outcome(outcome: DeliveryOutcome) {
    if let Some(collector) = COLLECTOR.get() {
        collector.record(outcome);
    }
}

/// Store the latest librdkafka statistics snapshot (10s cadence, not per
/// event). No-op unless [`init`] ran.
pub fn record_producer_stats(stats: ProducerStats) {
    if let Some(collector) = COLLECTOR.get() {
        *collector.producer_stats.lock().unwrap() = Some(stats);
    }
}

pub struct ReporterConfig {
    pub url: String,
    pub deployment: String,
    pub interval: Duration,
    pub request_timeout: Duration,
}

/// Install the global collector and spawn the report loop. Called once at
/// startup when `CAPTURE_KAFKA_MANAGER_URL` is set; a second call is ignored.
pub fn init(config: ReporterConfig) {
    let collector = Arc::new(Collector::default());
    if COLLECTOR.set(collector.clone()).is_err() {
        return;
    }
    let client = match reqwest::Client::builder()
        .timeout(config.request_timeout)
        .build()
    {
        Ok(client) => client,
        Err(e) => {
            // Reporter stays a no-op collector; capture is unaffected.
            warn!("kafka-manager reporter disabled, could not build HTTP client: {e:#}");
            return;
        }
    };
    tokio::spawn(report_loop(collector, client, config));
}

async fn report_loop(collector: Arc<Collector>, client: reqwest::Client, config: ReporterConfig) {
    let pod = std::env::var("HOSTNAME").unwrap_or_else(|_| "unknown".to_string());
    let endpoint = format!("{}/v1/health-reports", config.url.trim_end_matches('/'));
    let mut interval = tokio::time::interval(config.interval);
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    loop {
        interval.tick().await;
        let report = build_report(&collector, &pod, &config.deployment);
        send_report(&client, &endpoint, &report).await;
    }
}

fn build_report(collector: &Collector, pod: &str, deployment: &str) -> HealthReport {
    HealthReport {
        pod: pod.to_string(),
        deployment: deployment.to_string(),
        delivery: collector.delivery_counts(),
        producer: collector.producer_stats.lock().unwrap().clone(),
    }
}

async fn send_report(client: &reqwest::Client, endpoint: &str, report: &HealthReport) {
    match client.post(endpoint).json(report).send().await {
        Ok(response) if response.status().is_success() => {
            counter!("capture_manager_reports_sent_total").increment(1);
        }
        Ok(response) => {
            counter!("capture_manager_report_failures_total", "reason" => "http_status")
                .increment(1);
            debug!(
                "kafka-manager rejected health report: {}",
                response.status()
            );
        }
        Err(e) => {
            counter!("capture_manager_report_failures_total", "reason" => "unreachable")
                .increment(1);
            debug!("kafka-manager unreachable: {e:#}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::extract::State;
    use axum::routing::post;
    use axum::{Json, Router};

    #[test]
    fn record_hooks_are_noops_without_init() {
        // No test in this binary calls init(), so the hot-path hooks must
        // silently do nothing — this is the flag-off production state.
        assert!(!enabled());
        record_delivery_outcome(DeliveryOutcome::Delivered);
        record_producer_stats(ProducerStats::default());
    }

    #[test]
    fn build_report_snapshots_cumulative_counts() {
        let collector = Collector::default();
        collector.record(DeliveryOutcome::Delivered);
        collector.record(DeliveryOutcome::Delivered);
        collector.record(DeliveryOutcome::TimedOut);
        collector.record(DeliveryOutcome::TooLarge);

        let report = build_report(&collector, "pod-1", "capture");
        assert_eq!(report.delivery.ok, 2);
        assert_eq!(report.delivery.timed_out, 1);
        assert_eq!(report.delivery.too_large, 1);
        assert!(report.producer.is_none());

        collector.record(DeliveryOutcome::Delivered);
        let report = build_report(&collector, "pod-1", "capture");
        assert_eq!(report.delivery.ok, 3, "counts are cumulative");
    }

    #[tokio::test]
    async fn send_report_round_trips_to_manager() {
        let received: Arc<Mutex<Vec<HealthReport>>> = Arc::new(Mutex::new(Vec::new()));
        let sink = received.clone();
        let app = Router::new()
            .route(
                "/v1/health-reports",
                post(
                    |State(sink): State<Arc<Mutex<Vec<HealthReport>>>>,
                     Json(report): Json<HealthReport>| async move {
                        sink.lock().unwrap().push(report);
                        axum::http::StatusCode::NO_CONTENT
                    },
                ),
            )
            .with_state(sink);
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move { axum::serve(listener, app).await });

        let collector = Collector::default();
        collector.record(DeliveryOutcome::Delivered);
        let report = build_report(&collector, "pod-1", "capture");
        let client = reqwest::Client::new();
        send_report(
            &client,
            &format!("http://{addr}/v1/health-reports"),
            &report,
        )
        .await;

        let received = received.lock().unwrap();
        assert_eq!(received.len(), 1);
        assert_eq!(received[0].pod, "pod-1");
        assert_eq!(received[0].delivery.ok, 1);
    }

    #[tokio::test]
    async fn send_report_to_unreachable_manager_is_harmless() {
        let collector = Collector::default();
        let report = build_report(&collector, "pod-1", "capture");
        let client = reqwest::Client::builder()
            .timeout(Duration::from_millis(200))
            .build()
            .unwrap();
        // Reserved port with nothing listening: must return, not panic or hang.
        send_report(&client, "http://127.0.0.1:1/v1/health-reports", &report).await;
    }
}
