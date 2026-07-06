//! Self-instrumentation: exports this service's own `metrics::` facade output into
//! the PostHog metrics product, through the same fingerprint → Avro → Kafka path
//! customer OTLP metrics take — but entering one stage downstream of the HTTP
//! front door (direct sink write, no self-request, no auth round-trip). If the
//! HTTP layer is what's broken, these metrics keep flowing; if Kafka is broken,
//! nothing flows and the Prometheus scrape endpoint remains the black-box signal.
//!
//! The recorder is installed as a fanout peer of the Prometheus recorder (see
//! `common_metrics::setup_metrics_routes_with_secondary_recorder`), so every
//! existing `counter!` / `gauge!` / `histogram!` call site feeds both sinks —
//! no call site changes, and the `/metrics` scrape endpoint is unchanged.

use std::collections::HashMap;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use metrics::{Counter, Gauge, Histogram, Key, KeyName, Metadata, Recorder, SharedString, Unit};
use metrics_util::registry::{AtomicStorage, Registry};
use tracing::{error, info};
use uuid::Uuid;

use crate::kafka::KafkaSink;
use crate::metric_record::{compute_series_fingerprint, KafkaMetricRow};

pub const SERVICE_NAME: &str = "capture-logs";
const INSTRUMENTATION_SCOPE: &str = "capture-logs/internal-metrics";

/// Histogram observations are drained per export interval and re-bucketed into
/// explicit OTel bounds, chosen by the metric's naming convention. The Prometheus
/// exporter's single global ladder (milliseconds-shaped) makes `*_seconds`
/// histograms unreadable there; here each unit gets a fitting ladder.
const SECONDS_BOUNDS: &[f64] = &[
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0,
];
const MILLIS_BOUNDS: &[f64] = &[
    1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
];
const BYTES_BOUNDS: &[f64] = &[
    256.0, 1024.0, 4096.0, 16384.0, 65536.0, 262144.0, 1048576.0, 4194304.0, 16777216.0,
];

fn bounds_for(metric_name: &str) -> &'static [f64] {
    if metric_name.ends_with("_seconds") {
        SECONDS_BOUNDS
    } else if metric_name.contains("bytes") {
        BYTES_BOUNDS
    } else {
        // The `metrics` facade's timing guards record integer milliseconds; the
        // Prometheus default ladder here is ms-shaped, so it is the safe default.
        MILLIS_BOUNDS
    }
}

/// A `metrics::Recorder` backed by a plain atomic registry. Counters and gauges
/// hold their current value; histograms buffer raw observations until the next
/// drain (exported with delta temporality).
#[derive(Clone)]
pub struct InternalMetricsRecorder {
    registry: Arc<Registry<Key, AtomicStorage>>,
}

impl Default for InternalMetricsRecorder {
    fn default() -> Self {
        Self::new()
    }
}

impl InternalMetricsRecorder {
    pub fn new() -> Self {
        Self {
            registry: Arc::new(Registry::atomic()),
        }
    }

    /// Snapshot every instrument into metric rows. Counters and gauges export
    /// their current value (cumulative / point-in-time); histogram observations
    /// are consumed, so each drain emits only the interval's distribution.
    pub fn drain_rows(&self, resource_attributes: &HashMap<String, String>) -> Vec<KafkaMetricRow> {
        let now = Utc::now();
        let mut rows: Vec<KafkaMetricRow> = Vec::new();

        self.registry.visit_counters(|key, counter| {
            let mut row = base_row(key, "sum", now, resource_attributes);
            row.value = counter.load(Ordering::Relaxed) as f64;
            row.aggregation_temporality = "cumulative".to_string();
            row.is_monotonic = true;
            rows.push(row);
        });

        self.registry.visit_gauges(|key, gauge| {
            let mut row = base_row(key, "gauge", now, resource_attributes);
            row.value = f64::from_bits(gauge.load(Ordering::Relaxed));
            rows.push(row);
        });

        self.registry.visit_histograms(|key, bucket| {
            let mut values: Vec<f64> = Vec::new();
            bucket.clear_with(|chunk| values.extend_from_slice(chunk));
            if values.is_empty() {
                return;
            }
            let bounds = bounds_for(key.name());
            // OTel explicit-bounds semantics: bucket i counts values <= bounds[i],
            // with one overflow bucket past the last bound.
            let mut counts = vec![0i64; bounds.len() + 1];
            let mut sum = 0.0;
            for value in &values {
                sum += value;
                let idx = bounds.partition_point(|bound| bound < value);
                counts[idx] += 1;
            }
            let mut row = base_row(key, "histogram", now, resource_attributes);
            row.value = sum;
            row.count = values.len() as i64;
            row.histogram_bounds = bounds.to_vec();
            row.histogram_counts = counts;
            row.aggregation_temporality = "delta".to_string();
            rows.push(row);
        });

        rows
    }
}

fn base_row(
    key: &Key,
    metric_type: &str,
    timestamp: DateTime<Utc>,
    resource_attributes: &HashMap<String, String>,
) -> KafkaMetricRow {
    let attributes: HashMap<String, String> = key
        .labels()
        .map(|label| (label.key().to_string(), label.value().to_string()))
        .collect();
    let series_fingerprint = compute_series_fingerprint(
        key.name(),
        metric_type,
        SERVICE_NAME,
        resource_attributes,
        &attributes,
    );
    KafkaMetricRow {
        uuid: Uuid::new_v4().to_string(),
        trace_id: String::new(),
        span_id: String::new(),
        trace_flags: 0,
        timestamp,
        observed_timestamp: timestamp,
        service_name: SERVICE_NAME.to_string(),
        metric_name: key.name().to_string(),
        metric_type: metric_type.to_string(),
        value: 0.0,
        count: 0,
        histogram_bounds: Vec::new(),
        histogram_counts: Vec::new(),
        unit: String::new(),
        aggregation_temporality: String::new(),
        is_monotonic: false,
        resource_attributes: resource_attributes.clone(),
        instrumentation_scope: INSTRUMENTATION_SCOPE.to_string(),
        attributes,
        series_fingerprint,
    }
}

impl Recorder for InternalMetricsRecorder {
    fn describe_counter(&self, _: KeyName, _: Option<Unit>, _: SharedString) {}
    fn describe_gauge(&self, _: KeyName, _: Option<Unit>, _: SharedString) {}
    fn describe_histogram(&self, _: KeyName, _: Option<Unit>, _: SharedString) {}

    fn register_counter(&self, key: &Key, _: &Metadata<'_>) -> Counter {
        self.registry
            .get_or_create_counter(key, |c| Counter::from_arc(c.clone()))
    }

    fn register_gauge(&self, key: &Key, _: &Metadata<'_>) -> Gauge {
        self.registry
            .get_or_create_gauge(key, |g| Gauge::from_arc(g.clone()))
    }

    fn register_histogram(&self, key: &Key, _: &Metadata<'_>) -> Histogram {
        self.registry
            .get_or_create_histogram(key, |h| Histogram::from_arc(h.clone()))
    }
}

/// Per-replica series identity. Multi-replica cumulative counters collapse into
/// one series without `service.instance.id`, which makes every counter flip read
/// as a reset and inflates rate()/increase() by ~replica count.
fn resource_attributes() -> HashMap<String, String> {
    let mut attrs = HashMap::new();
    attrs.insert("service.name".to_string(), SERVICE_NAME.to_string());
    let instance_id = std::env::var("HOSTNAME").unwrap_or_else(|_| Uuid::new_v4().to_string());
    attrs.insert("service.instance.id".to_string(), instance_id);
    attrs
}

/// Periodically drain the recorder into the metrics Kafka topic. `token` scopes
/// the rows to the internal dogfood project, exactly as a customer token would.
/// Export failures are logged and never affect the ingest path.
pub fn spawn_exporter(
    recorder: InternalMetricsRecorder,
    sink: KafkaSink,
    token: String,
    interval: Duration,
) {
    info!(
        "internal metrics exporter enabled, exporting every {}s",
        interval.as_secs()
    );
    tokio::spawn(async move {
        let resource = resource_attributes();
        let mut ticker = tokio::time::interval(interval);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        // The first tick fires immediately; skip it so the first export carries
        // a full interval of data.
        ticker.tick().await;
        loop {
            ticker.tick().await;
            let rows = recorder.drain_rows(&resource);
            if rows.is_empty() {
                continue;
            }
            if let Err(err) = sink.write_metrics(&token, rows, 0, 0).await {
                error!("internal metrics export failed: {err}");
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use metrics::{counter, gauge, histogram};

    fn test_resource() -> HashMap<String, String> {
        HashMap::from([
            ("service.name".to_string(), SERVICE_NAME.to_string()),
            ("service.instance.id".to_string(), "pod-1".to_string()),
        ])
    }

    #[test]
    fn counter_exports_cumulative_monotonic_sum() {
        let recorder = InternalMetricsRecorder::new();
        metrics::with_local_recorder(&recorder, || {
            counter!("requests_total", "endpoint" => "/v1/logs").increment(3);
            counter!("requests_total", "endpoint" => "/v1/logs").increment(2);
        });

        let rows = recorder.drain_rows(&test_resource());
        assert_eq!(rows.len(), 1);
        let row = &rows[0];
        assert_eq!(row.metric_name, "requests_total");
        assert_eq!(row.metric_type, "sum");
        assert_eq!(row.value, 5.0);
        assert_eq!(row.aggregation_temporality, "cumulative");
        assert!(row.is_monotonic);
        assert_eq!(row.attributes["endpoint"], "/v1/logs");
        assert_eq!(row.service_name, SERVICE_NAME);
        assert_eq!(row.resource_attributes["service.instance.id"], "pod-1");

        // Cumulative: a second drain still reports the running total.
        let rows = recorder.drain_rows(&test_resource());
        assert_eq!(rows[0].value, 5.0);
        // Same series identity across drains — this is what rate()/increase() join on.
        assert_eq!(rows[0].series_fingerprint, row.series_fingerprint);
    }

    #[test]
    fn gauge_exports_point_in_time_value() {
        let recorder = InternalMetricsRecorder::new();
        metrics::with_local_recorder(&recorder, || {
            gauge!("queue_depth").set(42.5);
            gauge!("queue_depth").set(7.0);
        });

        let rows = recorder.drain_rows(&test_resource());
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].metric_type, "gauge");
        assert_eq!(rows[0].value, 7.0);
        assert!(!rows[0].is_monotonic);
    }

    #[test]
    fn histogram_exports_delta_buckets_and_drains() {
        let recorder = InternalMetricsRecorder::new();
        metrics::with_local_recorder(&recorder, || {
            let h = histogram!("request_duration_seconds");
            h.record(0.004);
            h.record(0.005); // boundary: le-inclusive, lands in the 0.005 bucket
            h.record(0.2);
            h.record(99.0); // beyond the last bound: overflow bucket
        });

        let rows = recorder.drain_rows(&test_resource());
        assert_eq!(rows.len(), 1);
        let row = &rows[0];
        assert_eq!(row.metric_type, "histogram");
        assert_eq!(row.aggregation_temporality, "delta");
        assert_eq!(row.count, 4);
        assert!((row.value - 99.209).abs() < 1e-9);
        assert_eq!(row.histogram_bounds, SECONDS_BOUNDS.to_vec());
        assert_eq!(row.histogram_counts.len(), SECONDS_BOUNDS.len() + 1);
        assert_eq!(row.histogram_counts[0], 2); // 0.004 and 0.005 (le 0.005)
        assert_eq!(row.histogram_counts[5], 1); // 0.2 -> le 0.25
        assert_eq!(row.histogram_counts[SECONDS_BOUNDS.len()], 1); // 99.0 overflow
        assert_eq!(row.histogram_counts.iter().sum::<i64>(), row.count);

        // Delta: observations were consumed, next drain emits nothing for it.
        assert!(recorder.drain_rows(&test_resource()).is_empty());
    }

    #[test]
    fn bounds_ladder_follows_metric_unit_convention() {
        assert_eq!(bounds_for("request_duration_seconds"), SECONDS_BOUNDS);
        assert_eq!(bounds_for("payload_bytes_uncompressed"), BYTES_BOUNDS);
        assert_eq!(bounds_for("handler_latency_ms"), MILLIS_BOUNDS);
    }

    #[test]
    fn label_permutation_does_not_change_fingerprint() {
        let recorder = InternalMetricsRecorder::new();
        metrics::with_local_recorder(&recorder, || {
            counter!("c", "a" => "1", "b" => "2").increment(1);
        });
        let recorder2 = InternalMetricsRecorder::new();
        metrics::with_local_recorder(&recorder2, || {
            counter!("c", "b" => "2", "a" => "1").increment(1);
        });
        let fp1 = recorder.drain_rows(&test_resource())[0].series_fingerprint;
        let fp2 = recorder2.drain_rows(&test_resource())[0].series_fingerprint;
        assert_eq!(fp1, fp2);
    }
}
