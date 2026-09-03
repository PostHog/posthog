use std::collections::HashMap;

use anyhow::{anyhow, Result};
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use bytes::Bytes;
use chrono::{TimeZone, Utc};
use metrics::counter;
use prometheus_rw_proto::prometheus::v1::{
    metric_metadata::MetricType, MetricMetadata, WriteRequest,
};
use prost::Message;
use serde::Deserialize;
use serde_json::json;
use tracing::{debug, error, instrument, warn};
use uuid::Uuid;

use crate::authorizer::Signal;
use crate::metric_record::{compute_series_fingerprint, override_timestamp, KafkaMetricRow};
use crate::service::Service;

const METRIC_NAME_LABEL: &str = "__name__";
const JOB_LABEL: &str = "job";
const INSTANCE_LABEL: &str = "instance";

/// Approximate in-memory/Avro cost of one row beyond its label data (uuid,
/// timestamps, type/temporality strings, map overhead). Used by
/// [`estimate_expanded_bytes`] so a request full of near-empty samples still
/// registers a per-row cost.
const ROW_OVERHEAD_BYTES: u64 = 256;

/// How much larger than the (already decompression-capped) request body the
/// expanded row set may be. Row building clones the series label map per
/// sample and the whole batch becomes a single Kafka message, so a 2 wire-byte
/// sample expands to hundreds of bytes — legitimate senders (Prometheus
/// defaults to 2k samples per send, vmagent to 10k rows per block) stay far
/// below this; only expansion-bomb payloads exceed it.
const MAX_EXPANSION_FACTOR: u64 = 16;

/// Decode a snappy-compressed Prometheus remote-write v1 payload, returning the
/// request and its decompressed size in bytes.
///
/// Prometheus sends `Content-Encoding: snappy` using the snappy *block* format
/// (not the framed format), so we decode the raw body ourselves — the global
/// `RequestDecompressionLayer` does not understand snappy.
///
/// The block format's length header is sender-controlled, so the claimed
/// decompressed size is checked against `max_decompressed_bytes` before any
/// allocation happens.
///
/// The size is returned because this route bypasses `RequestDecompressionLayer`,
/// so the request body is still compressed when the handler sees it. The OTLP and
/// logs paths report a body that layer already decompressed, and all three feed
/// the same quota and rate-limiting counters, so the measure has to match.
pub fn decode_write_request(
    body: &[u8],
    max_decompressed_bytes: usize,
) -> Result<(WriteRequest, u64)> {
    let claimed =
        snap::raw::decompress_len(body).map_err(|e| anyhow!("snappy decode failed: {e}"))?;
    if claimed > max_decompressed_bytes {
        return Err(anyhow!(
            "decompressed request body exceeds limit ({claimed} > {max_decompressed_bytes} bytes)"
        ));
    }
    let decompressed = snap::raw::Decoder::new()
        .decompress_vec(body)
        .map_err(|e| anyhow!("snappy decode failed: {e}"))?;
    let uncompressed_bytes = decompressed.len() as u64;
    let request = WriteRequest::decode(decompressed.as_slice())
        .map_err(|e| anyhow!("remote-write protobuf decode failed: {e}"))?;
    Ok((request, uncompressed_bytes))
}

/// Translate a decoded remote-write request into `KafkaMetricRow` records — the
/// same Avro shape the OTLP path produces, so the rest of the pipeline
/// (`ingestion-metrics` consumer → `clickhouse_metrics` → `metrics1`) is
/// unchanged. One row is emitted per sample. Returns the rows and the number of
/// samples whose timestamp was clamped by `override_timestamp`.
pub fn write_request_to_kafka_rows(req: WriteRequest) -> (Vec<KafkaMetricRow>, u64) {
    // Metric-family name -> declared (type, unit). Only populated when the
    // sender includes the optional metadata block (vmagent and many agents
    // omit it, so the name-suffix heuristic in `classify` is the primary path).
    let metadata = build_metadata_map(&req.metadata);

    let mut rows = Vec::new();
    let mut timestamps_overridden = 0u64;
    let mut dropped_series = 0u64;
    let mut dropped_samples = 0u64;

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

        // The vendored v1 proto deliberately skips native-histogram fields, so a
        // native-histogram series decodes to labels with no float samples and
        // yields no rows. Count it rather than let the whole request 204 as if
        // nothing were lost — the sender would otherwise drop the batch silently.
        if series.samples.is_empty() {
            dropped_series += 1;
            continue;
        }

        let declared = lookup_metadata(&metadata, &metric_name);
        let unit = declared.map(|(_, u)| u.clone()).unwrap_or_default();
        let (metric_type, is_monotonic, temporality) =
            classify(&metric_name, declared.map(|(t, _)| *t));

        let series_fingerprint = compute_series_fingerprint(
            &metric_name,
            metric_type,
            &service_name,
            &resource_attributes,
            &attributes,
        );

        for sample in series.samples {
            // Prometheus marks a series stale with a NaN payload and remote-write
            // forwards it (vmagent emits these by default on scrape failure or
            // series churn). The metrics pipeline has no stale-marker concept, and
            // a non-finite value survives the storage/query path uncaught —
            // `ifNull` never fires on NaN, and it corrupts rate/aggregate results.
            // Drop it here, as staleness-unaware receivers do.
            if !sample.value.is_finite() {
                dropped_samples += 1;
                continue;
            }

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
                unit: unit.clone(),
                aggregation_temporality: temporality.to_string(),
                is_monotonic,
                resource_attributes: resource_attributes.clone(),
                instrumentation_scope: String::new(),
                attributes: sample_attributes,
                series_fingerprint,
            });
        }
    }

    if dropped_series > 0 {
        counter!("capture_metrics_remote_write_dropped_series").increment(dropped_series);
        warn!(
            "Dropped {dropped_series} remote-write series with no ingestable samples (native histograms are not yet supported)"
        );
    }

    // Stale markers are routine, so this is counted (for volume visibility) but
    // not warned about, unlike the dropped-series case above.
    if dropped_samples > 0 {
        counter!("capture_metrics_remote_write_dropped_samples").increment(dropped_samples);
    }

    (rows, timestamps_overridden)
}

/// Build the metric-family-name -> (type, unit) map from the optional metadata
/// block. Entries with an unrecognized type are dropped. Shared by the row
/// builder and the expansion estimate so both agree on exactly which units get
/// cloned into rows.
fn build_metadata_map(metadata: &[MetricMetadata]) -> HashMap<String, (MetricType, String)> {
    metadata
        .iter()
        .filter_map(|m| {
            MetricType::try_from(m.r#type)
                .ok()
                .map(|t| (m.metric_family_name.clone(), (t, m.unit.clone())))
        })
        .collect()
}

/// Look up declared metadata, falling back to the base family name —
/// histogram/summary/counter families register under a base name while the
/// exposed series append `_bucket`/`_sum`/`_count`/`_total`.
fn lookup_metadata<'a>(
    metadata: &'a HashMap<String, (MetricType, String)>,
    name: &str,
) -> Option<&'a (MetricType, String)> {
    if let Some(m) = metadata.get(name) {
        return Some(m);
    }
    for suffix in ["_bucket", "_sum", "_count", "_total"] {
        if let Some(base) = name.strip_suffix(suffix) {
            if let Some(m) = metadata.get(base) {
                return Some(m);
            }
        }
    }
    None
}

/// Approximate the bytes the request expands to as `KafkaMetricRow`s: every
/// sample becomes a row carrying a clone of its series' label data, its declared
/// metadata unit, plus fixed per-row overhead. Wire size bounds none of these —
/// a zero-valued `Sample` is 2 wire bytes, and one fat label set or a fat
/// `MetricMetadata.unit` is encoded once but cloned per sample — so this is
/// checked against a multiple of the body limit before any row is built. Also
/// keeps the single Kafka message the batch becomes bounded.
pub fn estimate_expanded_bytes(req: &WriteRequest) -> u64 {
    let metadata = build_metadata_map(&req.metadata);
    req.timeseries
        .iter()
        .map(|series| {
            let label_bytes: u64 = series
                .labels
                .iter()
                .map(|l| (l.name.len() + l.value.len()) as u64)
                .sum();
            // The declared unit is cloned into every row (see `write_request_to_
            // kafka_rows`), so it must be part of the per-row cost — otherwise a
            // fat unit plus many compact samples slips under the cap and only
            // explodes at row-build time. Take the largest candidate rather than
            // one specific `__name__` label: nothing rejects a series carrying
            // several, the builder's loop keeps the last, and an estimate that
            // resolved a different one would under-count by the whole unit.
            let unit_bytes = series
                .labels
                .iter()
                .filter(|l| l.name == METRIC_NAME_LABEL)
                .filter_map(|l| lookup_metadata(&metadata, &l.value))
                .map(|(_, unit)| unit.len() as u64)
                .max()
                .unwrap_or(0);
            (series.samples.len() as u64) * (ROW_OVERHEAD_BYTES + label_bytes + unit_bytes)
        })
        .sum()
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

#[derive(Deserialize)]
pub struct RemoteWriteQueryParams {
    token: Option<String>,
}

/// Resolve the project token from (in order) the URL path, the Authorization
/// header (Bearer or bare), or the `token` query param — matching the
/// flexibility remote-write senders actually have.
fn extract_token(
    path_token: Option<String>,
    headers: &HeaderMap,
    query_token: Option<&str>,
) -> Option<String> {
    if let Some(token) = path_token {
        if !token.is_empty() {
            return Some(token);
        }
    }
    if let Some(auth) = headers.get("authorization").and_then(|v| v.to_str().ok()) {
        let token = auth
            .strip_prefix("Bearer ")
            .or_else(|| auth.strip_prefix("bearer "))
            .unwrap_or(auth)
            .trim();
        if !token.is_empty() {
            return Some(token.to_string());
        }
    }
    query_token.filter(|t| !t.is_empty()).map(str::to_string)
}

/// Prometheus remote-write v1 ingestion endpoint.
///
/// Snappy-decodes the protobuf body, maps it to `KafkaMetricRow` records, and
/// produces them through the shared `KafkaSink` so the rest of the pipeline is
/// identical to OTLP ingestion. Response codes follow remote-write semantics:
/// 204 on success, 400 on a permanent decode failure (sender drops the batch),
/// 5xx on a transient produce failure (sender retries).
#[instrument(skip_all, fields(
    token = tracing::field::Empty,
    user_agent = %headers.get("user-agent")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(""),
    content_length = %headers.get("content-length")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")))
]
pub async fn export_prometheus_remote_write_http(
    State(service): State<Service>,
    path_token: Option<Path<String>>,
    Query(query_params): Query<RemoteWriteQueryParams>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<StatusCode, (StatusCode, Json<serde_json::Value>)> {
    let token = match extract_token(
        path_token.map(|Path(t)| t),
        &headers,
        query_params.token.as_deref(),
    ) {
        Some(token) => token,
        None => {
            error!("No token provided");
            return Err((
                StatusCode::UNAUTHORIZED,
                Json(json!({"error": "No token provided"})),
            ));
        }
    };

    service
        .authorizer
        .authorize_token(&token, Signal::Metrics)?;

    tracing::Span::current().record("token", &token);

    let (write_request, uncompressed_bytes) =
        match decode_write_request(&body, service.max_request_body_size_bytes) {
            Ok(decoded) => decoded,
            Err(e) => {
                error!("Failed to decode remote-write request: {e}");
                return Err((
                    StatusCode::BAD_REQUEST,
                    Json(json!({ "error": format!("{e}") })),
                ));
            }
        };

    // 400, not 5xx: a batch that expands past the limit will never fit, so the
    // sender must drop it rather than retry it forever.
    let expanded = estimate_expanded_bytes(&write_request);
    let max_expanded = MAX_EXPANSION_FACTOR * service.max_request_body_size_bytes as u64;
    if expanded > max_expanded {
        error!(
            "Rejecting remote-write request expanding to ~{expanded} bytes (limit {max_expanded})"
        );
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "error": format!("request expands to too many samples (~{expanded} > {max_expanded} bytes); send smaller batches")
            })),
        ));
    }

    let (rows, timestamps_overridden) = write_request_to_kafka_rows(write_request);
    let row_count = rows.len();

    if let Err(e) = service
        .sink
        .write_metrics(&token, rows, uncompressed_bytes, timestamps_overridden)
        .await
    {
        error!("Failed to send remote-write metrics to Kafka: {e}");
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"error": "Internal server error"})),
        ));
    }

    debug!("Sent {row_count} remote-write data points to Kafka");
    Ok(StatusCode::NO_CONTENT)
}
