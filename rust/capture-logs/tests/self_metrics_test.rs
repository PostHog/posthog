use bytes::Bytes;
use capture_logs::self_metrics::{
    SelfMetricsRegistry, BYTES_PRODUCED, PRODUCER_QUEUE_DEPTH, RECORDS_PRODUCED,
};
use capture_logs::service::parse_otel_metrics_message;
use opentelemetry_proto::tonic::metrics::v1::metric::Data;

const START_NANOS: u64 = 1_700_000_000_000_000_000;
const NOW_NANOS: u64 = 1_700_000_060_000_000_000;

fn snapshot_bytes(registry: &SelfMetricsRegistry) -> Bytes {
    let body = registry.snapshot_otlp_json(NOW_NANOS, &[("service.name", "capture-logs")]);
    Bytes::from(serde_json::to_vec(&body).expect("serialize"))
}

/// The whole point of the self-push: what this registry serializes must round-trip
/// through the very ingest path capture-logs runs for customers. If the wire shape
/// drifts (string nanos, camelCase, temporality enum), ingestion silently loses our
/// own telemetry.
#[test]
fn snapshot_parses_and_flattens_through_the_ingest_path() {
    let registry = SelfMetricsRegistry::new(START_NANOS);
    registry.counter_add(&RECORDS_PRODUCED, &[("signal", "logs")], 10.0);
    registry.counter_add(&RECORDS_PRODUCED, &[("signal", "logs")], 15.0);
    registry.counter_add(&RECORDS_PRODUCED, &[("signal", "traces")], 5.0);
    registry.gauge_set(&PRODUCER_QUEUE_DEPTH, &[("producer", "logs")], 42.0);

    let request = parse_otel_metrics_message(&snapshot_bytes(&registry)).expect("parse");
    let resource_metrics = &request.resource_metrics[0];
    let scope_metrics = &resource_metrics.scope_metrics[0];

    let records = scope_metrics
        .metrics
        .iter()
        .find(|m| m.name == RECORDS_PRODUCED.name)
        .expect("records_produced present");
    let Some(Data::Sum(sum)) = &records.data else {
        panic!(
            "records_produced must parse as a sum, got {:?}",
            records.data
        );
    };
    assert!(sum.is_monotonic, "counters must be monotonic sums");
    assert_eq!(sum.aggregation_temporality, 2, "must be cumulative");
    assert_eq!(sum.data_points.len(), 2, "one data point per attribute set");

    // Adds accumulate into a cumulative total; flatten must carry value + attrs into rows.
    let (rows, _) = capture_logs::metric_record::flatten_metric(
        records.clone(),
        resource_metrics.resource.as_ref(),
        scope_metrics.scope.as_ref(),
    )
    .expect("flatten ok");
    // Attribute values arrive JSON-encoded in rows (ingest stores `"logs"` quoted) —
    // the same shape every pushed metric gets.
    let logs_row = rows
        .iter()
        .find(|r| r.attributes.get("signal").map(String::as_str) == Some("\"logs\""))
        .expect("logs row");
    assert_eq!(logs_row.value, 25.0);
    assert_eq!(logs_row.service_name, "capture-logs");
    assert!(logs_row.is_monotonic);

    let queue = scope_metrics
        .metrics
        .iter()
        .find(|m| m.name == PRODUCER_QUEUE_DEPTH.name)
        .expect("queue depth present");
    let Some(Data::Gauge(gauge)) = &queue.data else {
        panic!("queue depth must parse as a gauge, got {:?}", queue.data);
    };
    assert_eq!(gauge.data_points.len(), 1);

    let (rows, _) = capture_logs::metric_record::flatten_metric(
        queue.clone(),
        resource_metrics.resource.as_ref(),
        scope_metrics.scope.as_ref(),
    )
    .expect("flatten ok");
    assert_eq!(rows[0].value, 42.0);
    assert_eq!(
        rows[0].attributes.get("producer").map(String::as_str),
        Some("\"logs\"")
    );
}

/// Gauges must overwrite, not accumulate — a set-after-set that summed would report
/// a phantom ever-growing queue during an incident.
#[test]
fn gauge_set_overwrites_previous_value() {
    let registry = SelfMetricsRegistry::new(START_NANOS);
    registry.gauge_set(&PRODUCER_QUEUE_DEPTH, &[("producer", "logs")], 100.0);
    registry.gauge_set(&PRODUCER_QUEUE_DEPTH, &[("producer", "logs")], 7.0);

    let request = parse_otel_metrics_message(&snapshot_bytes(&registry)).expect("parse");
    let scope_metrics = &request.resource_metrics[0].scope_metrics[0];
    let queue = scope_metrics
        .metrics
        .iter()
        .find(|m| m.name == PRODUCER_QUEUE_DEPTH.name)
        .expect("present");
    let Some(Data::Gauge(gauge)) = &queue.data else {
        panic!("expected gauge");
    };
    let value = match gauge.data_points[0].value.as_ref().expect("value") {
        opentelemetry_proto::tonic::metrics::v1::number_data_point::Value::AsDouble(v) => *v,
        other => panic!("expected double, got {other:?}"),
    };
    assert_eq!(value, 7.0);
}

/// Process stats sampled at export time must produce a plausible CPU total: a
/// µs→s (or tick) conversion slip reads as absurd CPU seconds for a fresh process.
#[test]
fn process_stats_sample_produces_plausible_cpu_seconds() {
    let registry = SelfMetricsRegistry::new(START_NANOS);
    registry.sample_process_stats();

    let request = parse_otel_metrics_message(&snapshot_bytes(&registry)).expect("parse");
    let scope_metrics = &request.resource_metrics[0].scope_metrics[0];
    let cpu = scope_metrics
        .metrics
        .iter()
        .find(|m| m.name == "process_cpu_seconds_total")
        .expect("cpu metric present");
    let Some(Data::Sum(sum)) = &cpu.data else {
        panic!("cpu must be a sum");
    };
    let value = match sum.data_points[0].value.as_ref().expect("value") {
        opentelemetry_proto::tonic::metrics::v1::number_data_point::Value::AsDouble(v) => *v,
        other => panic!("expected double, got {other:?}"),
    };
    assert!(value > 0.0, "cpu seconds should be positive, got {value}");
    assert!(
        value < 3_600.0,
        "test process cannot have used an hour of CPU — unit conversion bug ({value})"
    );
}

/// An empty registry still snapshots valid OTLP (no metrics), so the export loop
/// never posts a body the ingest rejects.
#[test]
fn empty_registry_snapshot_still_parses() {
    let registry = SelfMetricsRegistry::new(START_NANOS);
    registry.counter_add(&BYTES_PRODUCED, &[("signal", "logs")], 0.0);

    parse_otel_metrics_message(&snapshot_bytes(&registry)).expect("parse");
}
