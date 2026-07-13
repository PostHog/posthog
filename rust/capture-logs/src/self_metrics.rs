use std::collections::BTreeMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use axum::{
    body::Body,
    extract::{MatchedPath, Request},
    middleware::Next,
    response::Response,
};
use serde_json::{json, Value};
use tracing::{info, warn};

use crate::config::Config;

/// Self-instrumentation pushed to PostHog's own metrics ingest, dogfooding the same
/// OTLP/JSON wire shape customers (and the Node.js services' OtlpJsonMetricExporter)
/// use, POSTed to /v1/metrics. The prom side of these signals keeps feeding the
/// scrape/VictoriaMetrics dashboards; this push makes the capture stage visible in
/// the PostHog metrics product next to the ingestion-stage twins.
///
/// Off unless both OTEL_METRICS_EXPORT_URL and OTEL_METRICS_EXPORT_TOKEN are set —
/// the same contract the Node.js services use — so nothing changes for deployments
/// that don't opt in.

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum InstrumentKind {
    /// Cumulative monotonic sum; `counter_add` accumulates, `sum_record` overwrites
    /// with an externally-cumulative total (process CPU).
    Sum,
    Gauge,
}

pub struct InstrumentDef {
    pub name: &'static str,
    pub description: &'static str,
    pub unit: &'static str,
    pub kind: InstrumentKind,
}

pub static RECORDS_PRODUCED: InstrumentDef = InstrumentDef {
    name: "capture_records_produced_total",
    description: "Records produced to Kafka by the capture service, by signal",
    unit: "",
    kind: InstrumentKind::Sum,
};

pub static BYTES_PRODUCED: InstrumentDef = InstrumentDef {
    name: "capture_bytes_produced_total",
    description: "Uncompressed payload bytes produced to Kafka by the capture service, by signal",
    unit: "By",
    kind: InstrumentKind::Sum,
};

pub static PRODUCE_ERRORS: InstrumentDef = InstrumentDef {
    name: "capture_produce_errors_total",
    description: "Kafka produce failures in the capture service, by signal",
    unit: "",
    kind: InstrumentKind::Sum,
};

pub static HTTP_REQUESTS: InstrumentDef = InstrumentDef {
    name: "capture_http_requests_total",
    description: "HTTP requests handled by the capture service, by route and status",
    unit: "",
    kind: InstrumentKind::Sum,
};

pub static PRODUCER_QUEUE_DEPTH: InstrumentDef = InstrumentDef {
    name: "capture_kafka_producer_queue_depth",
    description: "Messages waiting in the rdkafka producer queue, by producer",
    unit: "",
    kind: InstrumentKind::Gauge,
};

pub static PRODUCER_QUEUE_BYTES: InstrumentDef = InstrumentDef {
    name: "capture_kafka_producer_queue_bytes",
    description: "Bytes waiting in the rdkafka producer queue, by producer",
    unit: "By",
    kind: InstrumentKind::Gauge,
};

static PROCESS_CPU_SECONDS: InstrumentDef = InstrumentDef {
    name: "process_cpu_seconds_total",
    description: "Total user and system CPU time spent by the process in seconds",
    unit: "s",
    kind: InstrumentKind::Sum,
};

static PROCESS_RSS_BYTES: InstrumentDef = InstrumentDef {
    name: "process_resident_memory_bytes",
    description: "Resident memory size of the process in bytes",
    unit: "By",
    kind: InstrumentKind::Gauge,
};

/// (name, sorted attrs) — a distinct time series.
type SeriesKey = (&'static str, Vec<(&'static str, String)>);

struct SeriesState {
    def: &'static InstrumentDef,
    value: f64,
}

pub struct SelfMetricsRegistry {
    start_unix_nanos: u64,
    series: Mutex<BTreeMap<SeriesKey, SeriesState>>,
}

impl SelfMetricsRegistry {
    pub fn new(start_unix_nanos: u64) -> Self {
        Self {
            start_unix_nanos,
            series: Mutex::new(BTreeMap::new()),
        }
    }

    fn key(def: &'static InstrumentDef, attrs: &[(&'static str, &str)]) -> SeriesKey {
        let mut attrs: Vec<(&'static str, String)> =
            attrs.iter().map(|(k, v)| (*k, v.to_string())).collect();
        attrs.sort_unstable();
        (def.name, attrs)
    }

    fn upsert(
        &self,
        def: &'static InstrumentDef,
        attrs: &[(&'static str, &str)],
        apply: impl Fn(&mut f64),
    ) {
        // A poisoned lock means another metrics write panicked; telemetry must never
        // take the service down with it, so we just skip the record.
        let Ok(mut series) = self.series.lock() else {
            return;
        };
        let state = series
            .entry(Self::key(def, attrs))
            .or_insert(SeriesState { def, value: 0.0 });
        apply(&mut state.value);
    }

    pub fn counter_add(
        &self,
        def: &'static InstrumentDef,
        attrs: &[(&'static str, &str)],
        delta: f64,
    ) {
        self.upsert(def, attrs, |value| *value += delta);
    }

    /// Overwrite a sum series with an externally-cumulative total (e.g. process CPU
    /// read from the OS at sample time).
    pub fn sum_record(
        &self,
        def: &'static InstrumentDef,
        attrs: &[(&'static str, &str)],
        total: f64,
    ) {
        self.upsert(def, attrs, |value| *value = total);
    }

    pub fn gauge_set(
        &self,
        def: &'static InstrumentDef,
        attrs: &[(&'static str, &str)],
        value: f64,
    ) {
        self.upsert(def, attrs, |v| *v = value);
    }

    /// Sample process CPU/RSS into the registry; called once per export tick.
    pub fn sample_process_stats(&self) {
        if let Some(cpu_seconds) = process_cpu_seconds() {
            self.sum_record(&PROCESS_CPU_SECONDS, &[], cpu_seconds);
        }
        if let Some(rss) = process_rss_bytes() {
            self.gauge_set(&PROCESS_RSS_BYTES, &[], rss);
        }
    }

    /// Serialize the current state as OTLP/JSON in the exact wire shape our own
    /// /v1/metrics ingest parses (camelCase, unix nanos as decimal strings) —
    /// see tests/self_metrics_test.rs for the round-trip contract.
    pub fn snapshot_otlp_json(
        &self,
        now_unix_nanos: u64,
        resource_attrs: &[(&str, &str)],
    ) -> Value {
        let mut grouped: BTreeMap<&'static str, (&'static InstrumentDef, Vec<Value>)> =
            BTreeMap::new();
        {
            let Ok(series) = self.series.lock() else {
                return empty_snapshot(resource_attrs);
            };
            for ((name, attrs), state) in series.iter() {
                let data_point = json!({
                    "attributes": attrs
                        .iter()
                        .map(|(k, v)| json!({"key": k, "value": {"stringValue": v}}))
                        .collect::<Vec<_>>(),
                    "startTimeUnixNano": self.start_unix_nanos.to_string(),
                    "timeUnixNano": now_unix_nanos.to_string(),
                    "asDouble": state.value,
                });
                grouped
                    .entry(name)
                    .or_insert((state.def, Vec::new()))
                    .1
                    .push(data_point);
            }
        }

        let metrics: Vec<Value> = grouped
            .into_values()
            .map(|(def, data_points)| {
                let mut metric = json!({
                    "name": def.name,
                    "description": def.description,
                    "unit": def.unit,
                });
                let data = match def.kind {
                    InstrumentKind::Sum => json!({
                        "sum": {
                            "dataPoints": data_points,
                            // OTLP proto enum: 2 = cumulative.
                            "aggregationTemporality": 2,
                            "isMonotonic": true,
                        }
                    }),
                    InstrumentKind::Gauge => json!({
                        "gauge": { "dataPoints": data_points }
                    }),
                };
                merge_objects(&mut metric, data);
                metric
            })
            .collect();

        let mut snapshot = empty_snapshot(resource_attrs);
        snapshot["resourceMetrics"][0]["scopeMetrics"][0]["metrics"] = Value::Array(metrics);
        snapshot
    }
}

fn empty_snapshot(resource_attrs: &[(&str, &str)]) -> Value {
    json!({
        "resourceMetrics": [{
            "resource": {
                "attributes": resource_attrs
                    .iter()
                    .map(|(k, v)| json!({"key": k, "value": {"stringValue": v}}))
                    .collect::<Vec<_>>(),
            },
            "scopeMetrics": [{
                "scope": {"name": "capture-logs-self"},
                "metrics": [],
            }],
        }],
    })
}

fn merge_objects(target: &mut Value, source: Value) {
    if let (Some(target), Value::Object(source)) = (target.as_object_mut(), source) {
        target.extend(source);
    }
}

fn now_unix_nanos() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0)
}

/// Cumulative user+system CPU seconds via getrusage(2) — POSIX, works on Linux and macOS.
fn process_cpu_seconds() -> Option<f64> {
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: getrusage fills the struct we hand it; we only read it on success.
    let rc = unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) };
    if rc != 0 {
        return None;
    }
    let usage = unsafe { usage.assume_init() };
    let seconds = |tv: libc::timeval| tv.tv_sec as f64 + tv.tv_usec as f64 / 1e6;
    Some(seconds(usage.ru_utime) + seconds(usage.ru_stime))
}

/// Current RSS from /proc — Linux only, where production runs; None elsewhere.
fn process_rss_bytes() -> Option<f64> {
    let statm = std::fs::read_to_string("/proc/self/statm").ok()?;
    let resident_pages: f64 = statm.split_whitespace().nth(1)?.parse().ok()?;
    // SAFETY: sysconf with a valid constant is always safe to call.
    let page_size = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
    if page_size <= 0 {
        return None;
    }
    Some(resident_pages * page_size as f64)
}

/// OTLP-pushed twin of the prom `http_requests_total` middleware counter, keyed by
/// matched route (never the raw path — the datadog `:token` route would explode
/// series cardinality otherwise).
pub async fn track_http_requests(req: Request<Body>, next: Next) -> Response {
    let path = req
        .extensions()
        .get::<MatchedPath>()
        .map(|p| p.as_str().to_owned())
        .unwrap_or_else(|| "unknown".to_owned());
    let method = req.method().to_string();
    let response = next.run(req).await;
    let status = response.status().as_u16().to_string();
    global().counter_add(
        &HTTP_REQUESTS,
        &[("method", &method), ("path", &path), ("status", &status)],
        1.0,
    );
    response
}

static GLOBAL: OnceLock<SelfMetricsRegistry> = OnceLock::new();

pub fn global() -> &'static SelfMetricsRegistry {
    GLOBAL.get_or_init(|| SelfMetricsRegistry::new(now_unix_nanos()))
}

/// Spawn the periodic export loop if OTEL_METRICS_EXPORT_URL/TOKEN are configured.
pub fn spawn_exporter_if_configured(config: &Config) {
    let (Some(url), Some(token)) = (
        config.otel_metrics_export_url.clone(),
        config.otel_metrics_export_token.clone(),
    ) else {
        return;
    };
    let interval = Duration::from_millis(config.otel_metrics_export_interval_ms);
    let service_name = config.otel_service_name.clone();
    info!("Starting OTLP self-metrics push to {url}");

    tokio::spawn(async move {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .expect("reqwest client");
        let instance_id = std::env::var("HOSTNAME").unwrap_or_else(|_| "unknown".to_string());
        let version = std::env::var("COMMIT_SHA").unwrap_or_else(|_| "dev".to_string());
        let mut ticker = tokio::time::interval(interval);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            ticker.tick().await;
            let registry = global();
            registry.sample_process_stats();
            let body = registry.snapshot_otlp_json(
                now_unix_nanos(),
                &[
                    ("service.name", service_name.as_str()),
                    ("service.version", version.as_str()),
                    // Per-replica identity: without it every pod shares one series and
                    // their interleaved cumulative counters read as constant resets.
                    ("service.instance.id", instance_id.as_str()),
                ],
            );
            let result = client
                .post(&url)
                .bearer_auth(&token)
                .json(&body)
                .send()
                .await;
            match result {
                Ok(response) if response.status().is_success() => {}
                Ok(response) => {
                    warn!("OTLP self-metrics push rejected: {}", response.status());
                }
                Err(error) => {
                    warn!("OTLP self-metrics push failed: {error}");
                }
            }
        }
    });
}
