use std::collections::HashMap;

use anyhow::{anyhow, Result};
use chrono::{TimeZone, Utc};
use prometheus_rw_proto::prometheus::v1::{metric_metadata::MetricType, WriteRequest};
use prost::Message;
use serde_json::json;
use uuid::Uuid;

use crate::metric_record::{override_timestamp, KafkaMetricRow};

const METRIC_NAME_LABEL: &str = "__name__";
const JOB_LABEL: &str = "job";
const INSTANCE_LABEL: &str = "instance";

/// Decode a snappy-compressed Prometheus remote-write v1 payload.
///
/// Prometheus sends `Content-Encoding: snappy` using the snappy *block* format
/// (not the framed format), so we decode the raw body ourselves — the global
/// `RequestDecompressionLayer` does not understand snappy.
pub fn decode_write_request(body: &[u8]) -> Result<WriteRequest> {
    let decompressed = snap::raw::Decoder::new()
        .decompress_vec(body)
        .map_err(|e| anyhow!("snappy decode failed: {e}"))?;
    WriteRequest::decode(decompressed.as_slice())
        .map_err(|e| anyhow!("remote-write protobuf decode failed: {e}"))
}

/// Translate a decoded remote-write request into `KafkaMetricRow` records — the
/// same Avro shape the OTLP path produces, so the rest of the pipeline
/// (`ingestion-metrics` → consumer → `clickhouse_metrics` → `metrics1`) is
/// unchanged. One row is emitted per sample. Returns the rows and the number of
/// samples whose timestamp was clamped by `override_timestamp`.
pub fn write_request_to_kafka_rows(req: WriteRequest) -> (Vec<KafkaMetricRow>, u64) {
    // Metric-family name -> declared type. Only populated when the sender
    // includes the optional metadata block (vmagent and many agents omit it,
    // so the name-suffix heuristic in `classify` is the primary path).
    let metadata: HashMap<String, MetricType> = req
        .metadata
        .iter()
        .filter_map(|m| {
            MetricType::try_from(m.r#type)
                .ok()
                .map(|t| (m.metric_family_name.clone(), t))
        })
        .collect();

    let mut rows = Vec::new();
    let mut timestamps_overridden = 0u64;

    for series in req.timeseries {
        let mut metric_name = String::new();
        let mut service_name = String::new();
        let mut resource_attributes: HashMap<String, String> = HashMap::new();
        let mut attributes: HashMap<String, String> = HashMap::new();

        for label in series.labels {
            match label.name.as_str() {
                METRIC_NAME_LABEL => metric_name = label.value,
                // Map Prometheus topology labels onto OTel resource semantics so
                // `service_name` populates the same way it does for OTLP. Map
                // values are JSON-encoded to match the OTLP/Datadog paths — the
                // ClickHouse MV applies JSONExtractString to them.
                JOB_LABEL => {
                    service_name = label.value.clone();
                    resource_attributes
                        .insert("service.name".to_string(), json!(label.value).to_string());
                }
                INSTANCE_LABEL => {
                    resource_attributes.insert(
                        "service.instance.id".to_string(),
                        json!(label.value).to_string(),
                    );
                }
                _ => {
                    attributes.insert(label.name, json!(label.value).to_string());
                }
            }
        }

        // A series with no metric name is unusable; skip it.
        if metric_name.is_empty() {
            continue;
        }

        let (metric_type, is_monotonic, temporality) =
            classify(&metric_name, lookup_type(&metadata, &metric_name));

        for sample in series.samples {
            // Remote-write sample timestamps are milliseconds since the epoch.
            let raw_timestamp = Utc
                .timestamp_millis_opt(sample.timestamp)
                .single()
                .unwrap_or_else(Utc::now);
            let (timestamp, original_timestamp) = override_timestamp(raw_timestamp);

            let mut sample_attributes = attributes.clone();
            if let Some(original) = original_timestamp {
                timestamps_overridden += 1;
                sample_attributes.insert("$originalTimestamp".to_string(), original.to_rfc3339());
            }

            rows.push(KafkaMetricRow {
                uuid: Uuid::now_v7().to_string(),
                trace_id: String::new(),
                span_id: String::new(),
                trace_flags: 0,
                timestamp,
                observed_timestamp: Utc::now(),
                service_name: service_name.clone(),
                metric_name: metric_name.clone(),
                metric_type: metric_type.to_string(),
                value: sample.value,
                count: 1,
                histogram_bounds: Vec::new(),
                histogram_counts: Vec::new(),
                unit: String::new(),
                aggregation_temporality: temporality.to_string(),
                is_monotonic,
                resource_attributes: resource_attributes.clone(),
                instrumentation_scope: String::new(),
                attributes: sample_attributes,
            });
        }
    }

    (rows, timestamps_overridden)
}

/// Look up a declared metric type, falling back to the base family name —
/// histogram/summary/counter families register under a base name while the
/// exposed series append `_bucket`/`_sum`/`_count`/`_total`.
fn lookup_type(metadata: &HashMap<String, MetricType>, name: &str) -> Option<MetricType> {
    if let Some(t) = metadata.get(name) {
        return Some(*t);
    }
    for suffix in ["_bucket", "_sum", "_count", "_total"] {
        if let Some(base) = name.strip_suffix(suffix) {
            if let Some(t) = metadata.get(base) {
                return Some(*t);
            }
        }
    }
    None
}

/// Infer (metric_type, is_monotonic, aggregation_temporality) for a series.
///
/// Prometheus counters, histograms and summaries are cumulative. RW v1 carries
/// no per-sample type, so declared metadata (when present) takes precedence and
/// the `_total`/`_bucket`/`_sum`/`_count` suffix heuristic is the fallback.
/// Classic histograms/summaries are stored as their decomposed scalar component
/// series (queryable via PromQL); native-histogram array reconstruction is
/// deferred.
fn classify(name: &str, declared: Option<MetricType>) -> (&'static str, bool, &'static str) {
    if let Some(t) = declared {
        match t {
            MetricType::Counter => return ("sum", true, "cumulative"),
            MetricType::Gauge => return ("gauge", false, ""),
            // Histogram/Summary expose decomposed cumulative component series;
            // type each component via the suffix heuristic below.
            _ => {}
        }
    }

    if name.ends_with("_total")
        || name.ends_with("_bucket")
        || name.ends_with("_count")
        || name.ends_with("_sum")
    {
        ("sum", true, "cumulative")
    } else {
        ("gauge", false, "")
    }
}
