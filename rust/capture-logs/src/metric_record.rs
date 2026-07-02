use std::collections::HashMap;
use std::hash::Hasher;

use anyhow::Result;
use base64::{prelude::BASE64_STANDARD, Engine};
use chrono::serde::ts_microseconds;
use chrono::DateTime;
use chrono::TimeDelta;
use chrono::Utc;
use opentelemetry_proto::tonic::{
    common::v1::{
        any_value::{self, Value},
        AnyValue, InstrumentationScope, KeyValue,
    },
    metrics::v1::{
        exponential_histogram_data_point::Buckets, metric::Data, AggregationTemporality, Metric,
    },
    resource::v1::Resource,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as JsonValue};
use siphasher::sip::SipHasher13;
use tracing::debug;
use uuid::Uuid;

use crate::log_record::{extract_span_id, extract_trace_id};

#[derive(Debug, Serialize, Deserialize)]
pub struct KafkaMetricRow {
    pub uuid: String,
    pub trace_id: String,
    pub span_id: String,
    pub trace_flags: u32,
    #[serde(with = "ts_microseconds")]
    pub timestamp: DateTime<Utc>,
    #[serde(with = "ts_microseconds")]
    pub observed_timestamp: DateTime<Utc>,
    pub service_name: String,
    pub metric_name: String,
    pub metric_type: String,
    pub value: f64,
    pub count: i64,
    pub histogram_bounds: Vec<f64>,
    pub histogram_counts: Vec<i64>,
    pub unit: String,
    pub aggregation_temporality: String,
    pub is_monotonic: bool,
    pub resource_attributes: HashMap<String, String>,
    pub instrumentation_scope: String,
    pub attributes: HashMap<String, String>,
    /// Stable per-series identity, assigned here at ingest and stored verbatim by
    /// ClickHouse (which never recomputes it). Links a sample to its series at read
    /// time. i64 carries the u64 hash bits to fit Avro's `long`.
    pub series_fingerprint: i64,
}

/// Flatten an OTEL Metric into one or more KafkaMetricRow records.
/// Each data point in the metric becomes a separate row.
pub fn flatten_metric(
    metric: Metric,
    resource: Option<&Resource>,
    scope: Option<&InstrumentationScope>,
) -> Result<(Vec<KafkaMetricRow>, u64)> {
    let metric_name = metric.name;
    let unit = metric.unit;
    let resource_attributes = extract_resource_attributes(resource);
    let service_name = extract_string_from_map(&resource_attributes, "service.name");
    let instrumentation_scope = match scope {
        Some(s) => format!("{}@{}", s.name, s.version),
        None => String::new(),
    };

    let mut rows = Vec::new();
    let mut timestamps_overridden: u64 = 0;

    let Some(data) = metric.data else {
        return Ok((rows, timestamps_overridden));
    };

    match data {
        Data::Gauge(gauge) => {
            for dp in gauge.data_points {
                let (row, overridden) = build_number_row(
                    &metric_name,
                    "gauge",
                    &unit,
                    &resource_attributes,
                    &service_name,
                    &instrumentation_scope,
                    dp.time_unix_nano,
                    dp.start_time_unix_nano,
                    &dp.attributes,
                    number_value(&dp.value),
                    None,
                    None,
                    &dp.exemplars,
                    dp.flags,
                )?;
                if overridden {
                    timestamps_overridden += 1;
                }
                rows.push(row);
            }
        }
        Data::Sum(sum) => {
            let temporality = temporality_str(sum.aggregation_temporality);
            let is_monotonic = sum.is_monotonic;
            for dp in sum.data_points {
                let (mut row, overridden) = build_number_row(
                    &metric_name,
                    "sum",
                    &unit,
                    &resource_attributes,
                    &service_name,
                    &instrumentation_scope,
                    dp.time_unix_nano,
                    dp.start_time_unix_nano,
                    &dp.attributes,
                    number_value(&dp.value),
                    None,
                    None,
                    &dp.exemplars,
                    dp.flags,
                )?;
                row.aggregation_temporality = temporality.clone();
                row.is_monotonic = is_monotonic;
                if overridden {
                    timestamps_overridden += 1;
                }
                rows.push(row);
            }
        }
        Data::Histogram(hist) => {
            let temporality = temporality_str(hist.aggregation_temporality);
            for dp in hist.data_points {
                let value = dp.sum.unwrap_or(0.0);
                let count = dp.count as i64;
                let bounds = dp.explicit_bounds.clone();
                let counts: Vec<i64> = dp.bucket_counts.iter().map(|c| *c as i64).collect();

                let (mut row, overridden) = build_number_row(
                    &metric_name,
                    "histogram",
                    &unit,
                    &resource_attributes,
                    &service_name,
                    &instrumentation_scope,
                    dp.time_unix_nano,
                    dp.start_time_unix_nano,
                    &dp.attributes,
                    value,
                    Some(bounds),
                    Some(counts),
                    &dp.exemplars,
                    dp.flags,
                )?;
                row.count = count;
                row.aggregation_temporality = temporality.clone();
                if overridden {
                    timestamps_overridden += 1;
                }
                rows.push(row);
            }
        }
        Data::ExponentialHistogram(hist) => {
            let temporality = temporality_str(hist.aggregation_temporality);
            for dp in hist.data_points {
                let value = dp.sum.unwrap_or(0.0);
                let count = dp.count as i64;

                // Flatten exponential histogram buckets into explicit bounds/counts
                let (bounds, counts) = flatten_exponential_buckets(
                    dp.scale,
                    dp.zero_count,
                    &dp.positive,
                    &dp.negative,
                );

                let (mut row, overridden) = build_number_row(
                    &metric_name,
                    "exponential_histogram",
                    &unit,
                    &resource_attributes,
                    &service_name,
                    &instrumentation_scope,
                    dp.time_unix_nano,
                    dp.start_time_unix_nano,
                    &dp.attributes,
                    value,
                    Some(bounds),
                    Some(counts),
                    &dp.exemplars,
                    dp.flags,
                )?;
                row.count = count;
                row.aggregation_temporality = temporality.clone();
                if overridden {
                    timestamps_overridden += 1;
                }
                rows.push(row);
            }
        }
        Data::Summary(summary) => {
            for dp in summary.data_points {
                let value = dp.sum;
                let count = dp.count as i64;

                // Store quantile values as histogram_bounds (quantiles) and histogram_counts (values)
                let bounds: Vec<f64> = dp.quantile_values.iter().map(|q| q.quantile).collect();
                let counts: Vec<i64> = dp
                    .quantile_values
                    .iter()
                    .map(|q| q.value.to_bits() as i64)
                    .collect();

                let (mut row, overridden) = build_number_row(
                    &metric_name,
                    "summary",
                    &unit,
                    &resource_attributes,
                    &service_name,
                    &instrumentation_scope,
                    dp.time_unix_nano,
                    dp.start_time_unix_nano,
                    &dp.attributes,
                    value,
                    Some(bounds),
                    Some(counts),
                    &[],
                    dp.flags,
                )?;
                row.count = count;
                if overridden {
                    timestamps_overridden += 1;
                }
                rows.push(row);
            }
        }
    }

    debug!(
        "Flattened metric '{}' into {} rows",
        metric_name,
        rows.len()
    );
    Ok((rows, timestamps_overridden))
}

#[allow(clippy::too_many_arguments)]
fn build_number_row(
    metric_name: &str,
    metric_type: &str,
    unit: &str,
    resource_attributes: &HashMap<String, String>,
    service_name: &str,
    instrumentation_scope: &str,
    time_unix_nano: u64,
    _start_time_unix_nano: u64,
    dp_attributes: &[KeyValue],
    value: f64,
    histogram_bounds: Option<Vec<f64>>,
    histogram_counts: Option<Vec<i64>>,
    exemplars: &[opentelemetry_proto::tonic::metrics::v1::Exemplar],
    flags: u32,
) -> Result<(KafkaMetricRow, bool)> {
    // OTel exemplars attach trace context (and per-bucket trace context on histograms) to
    // data points. V1 picks the first exemplar with a spec-conformant 16-byte trace_id and
    // runs it through the shared extract_trace_id / extract_span_id helpers (same encoding
    // path as log_record / trace_record). Filtering by length up front avoids the case
    // where a malformed exemplar earlier in the vec would shadow a valid one — exemplar
    // selection is a metrics-specific concern with no precedent in logs/traces, which
    // each carry a single trace_id field. Per-bucket attribution on histograms is lossy
    // in this representation; revisit when we add a multi-row or array exemplar column.
    let (exemplar_trace_id, exemplar_span_id) = exemplars
        .iter()
        .find(|e| e.trace_id.len() == 16)
        .map(|e| {
            (
                BASE64_STANDARD.encode(extract_trace_id(&e.trace_id)),
                BASE64_STANDARD.encode(extract_span_id(&e.span_id)),
            )
        })
        .unwrap_or_default();
    let raw_timestamp = match time_unix_nano {
        0 => Utc::now(),
        _ => DateTime::<Utc>::from_timestamp_nanos(time_unix_nano.try_into()?),
    };

    let (timestamp, original_timestamp) = override_timestamp(raw_timestamp);
    let was_overridden = original_timestamp.is_some();

    let mut attributes: HashMap<String, String> = dp_attributes
        .iter()
        .map(|kv| {
            (
                kv.key.clone(),
                any_value_to_string(kv.value.clone().unwrap_or(AnyValue {
                    value: Some(Value::StringValue(String::new())),
                })),
            )
        })
        .collect();

    // Identity is assigned once, here. Computed before the synthetic $originalTimestamp
    // is added so an overridden timestamp never splits a series.
    let series_fingerprint = compute_series_fingerprint(
        metric_name,
        metric_type,
        service_name,
        resource_attributes,
        &attributes,
    );

    if let Some(original) = original_timestamp {
        attributes.insert("$originalTimestamp".to_string(), original.to_rfc3339());
    }

    let observed_timestamp = Utc::now();

    let row = KafkaMetricRow {
        uuid: Uuid::now_v7().to_string(),
        trace_id: exemplar_trace_id,
        span_id: exemplar_span_id,
        trace_flags: flags,
        timestamp,
        observed_timestamp,
        service_name: service_name.to_string(),
        metric_name: metric_name.to_string(),
        metric_type: metric_type.to_string(),
        value,
        count: 1,
        histogram_bounds: histogram_bounds.unwrap_or_default(),
        histogram_counts: histogram_counts.unwrap_or_default(),
        unit: unit.to_string(),
        aggregation_temporality: String::new(),
        is_monotonic: false,
        resource_attributes: resource_attributes.clone(),
        instrumentation_scope: instrumentation_scope.to_string(),
        attributes,
        series_fingerprint,
    };

    Ok((row, was_overridden))
}

/// Stable, order-independent 64-bit identity for a metric series, assigned at ingest.
///
/// Computed once here and carried to ClickHouse as `series_fingerprint`, so storage
/// never recomputes it — the TSDB / Snuffle-default approach. The hash is internal
/// (samples link to their series within this system only), so it need not match any
/// ClickHouse hash; any deterministic algorithm works. SipHash-1-3 with a fixed key is
/// stable across builds. Returned as i64 (the u64 bit pattern) to fit Avro's `long`;
/// ClickHouse reinterprets it back to UInt64.
///
/// `metric_type` is part of the identity: a gauge and a sum sharing a name and labels
/// are different series, and `metric_series` stores `metric_type` per fingerprint — so
/// omitting it would let one type's row silently overwrite the other's on dedup.
fn compute_series_fingerprint(
    metric_name: &str,
    metric_type: &str,
    service_name: &str,
    resource_attributes: &HashMap<String, String>,
    attributes: &HashMap<String, String>,
) -> i64 {
    let mut hasher = SipHasher13::new();
    hash_str(&mut hasher, metric_name);
    hash_str(&mut hasher, metric_type);
    hash_str(&mut hasher, service_name);
    hash_sorted_map(&mut hasher, resource_attributes);
    hash_sorted_map(&mut hasher, attributes);
    hasher.finish() as i64
}

/// Length-prefixed so e.g. {"ab":"c"} and {"a":"bc"} can never collide. Lengths are
/// written little-endian (not native `write_u64`) so the id is identical on any host.
fn hash_str(hasher: &mut SipHasher13, s: &str) {
    hasher.write(&(s.len() as u64).to_le_bytes());
    hasher.write(s.as_bytes());
}

/// Sort by key so HashMap iteration order can never change the fingerprint.
fn hash_sorted_map(hasher: &mut SipHasher13, map: &HashMap<String, String>) {
    let mut pairs: Vec<(&str, &str)> = map.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
    pairs.sort_unstable();
    hasher.write(&(pairs.len() as u64).to_le_bytes());
    for (key, value) in pairs {
        hash_str(hasher, key);
        hash_str(hasher, value);
    }
}

/// Flatten exponential histogram buckets into explicit bounds and counts.
fn flatten_exponential_buckets(
    scale: i32,
    zero_count: u64,
    positive: &Option<Buckets>,
    negative: &Option<Buckets>,
) -> (Vec<f64>, Vec<i64>) {
    let mut bounds = Vec::new();
    let mut counts = Vec::new();

    // Add zero bucket
    if zero_count > 0 {
        bounds.push(0.0);
        counts.push(zero_count as i64);
    }

    let base = 2.0_f64.powf(2.0_f64.powi(-scale));

    if let Some(neg) = negative {
        for (i, &count) in neg.bucket_counts.iter().enumerate() {
            let idx = neg.offset as i64 + i as i64;
            let bound = -base.powf(idx as f64);
            bounds.push(bound);
            counts.push(count as i64);
        }
    }

    if let Some(pos) = positive {
        for (i, &count) in pos.bucket_counts.iter().enumerate() {
            let idx = pos.offset as i64 + i as i64;
            let bound = base.powf(idx as f64);
            bounds.push(bound);
            counts.push(count as i64);
        }
    }

    (bounds, counts)
}

fn number_value(
    value: &Option<opentelemetry_proto::tonic::metrics::v1::number_data_point::Value>,
) -> f64 {
    match value {
        Some(opentelemetry_proto::tonic::metrics::v1::number_data_point::Value::AsDouble(d)) => *d,
        Some(opentelemetry_proto::tonic::metrics::v1::number_data_point::Value::AsInt(i)) => {
            *i as f64
        }
        None => 0.0,
    }
}

fn temporality_str(temporality: i32) -> String {
    match AggregationTemporality::try_from(temporality) {
        Ok(AggregationTemporality::Delta) => "delta".to_string(),
        Ok(AggregationTemporality::Cumulative) => "cumulative".to_string(),
        _ => "unspecified".to_string(),
    }
}

const TIMESTAMP_OVERRIDE_HOURS: i64 = 24;

pub fn override_timestamp(timestamp: DateTime<Utc>) -> (DateTime<Utc>, Option<DateTime<Utc>>) {
    let now = Utc::now();
    let max_delta = TimeDelta::hours(TIMESTAMP_OVERRIDE_HOURS);

    if timestamp < now - max_delta || timestamp > now + max_delta {
        (now, Some(timestamp))
    } else {
        (timestamp, None)
    }
}

fn extract_string_from_map(attributes: &HashMap<String, String>, key: &str) -> String {
    if let Some(value) = attributes.get(key) {
        if let Ok(JsonValue::String(value)) = serde_json::from_str::<JsonValue>(value) {
            value.to_string()
        } else {
            value.to_string()
        }
    } else {
        String::new()
    }
}

fn extract_resource_attributes(resource: Option<&Resource>) -> HashMap<String, String> {
    let Some(resource) = resource else {
        return HashMap::new();
    };

    resource
        .attributes
        .iter()
        .map(|kv| {
            (
                kv.key.clone(),
                any_value_to_string(kv.value.clone().unwrap_or(AnyValue {
                    value: Some(Value::StringValue(String::new())),
                })),
            )
        })
        .collect()
}

fn any_value_to_json(value: AnyValue) -> JsonValue {
    match value.value {
        Some(value_enum) => match value_enum {
            any_value::Value::StringValue(s) => json!(s),
            any_value::Value::BoolValue(b) => json!(b),
            any_value::Value::IntValue(i) => json!(i),
            any_value::Value::DoubleValue(d) => json!(d),
            any_value::Value::ArrayValue(arr) => {
                json!(arr
                    .values
                    .into_iter()
                    .map(any_value_to_json)
                    .collect::<Vec<_>>())
            }
            any_value::Value::KvlistValue(kvlist) => {
                let mut map = HashMap::new();
                for kv in kvlist.values.into_iter() {
                    if let Some(v) = kv.value {
                        map.insert(kv.key.clone(), any_value_to_json(v));
                    }
                }
                json!(map)
            }
            any_value::Value::BytesValue(b) => {
                json!(BASE64_STANDARD.encode(b))
            }
        },
        None => JsonValue::Null,
    }
}

fn any_value_to_string(value: AnyValue) -> String {
    any_value_to_json(value).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_override_timestamp_within_range_is_unchanged() {
        let now = Utc::now();
        let one_hour_ago = now - TimeDelta::hours(1);
        let (final_ts, original) = override_timestamp(one_hour_ago);
        assert_eq!(final_ts, one_hour_ago);
        assert!(original.is_none());
    }

    #[test]
    fn test_override_timestamp_far_past_is_overridden() {
        let now = Utc::now();
        let two_days_ago = now - TimeDelta::hours(48);
        let (final_ts, original) = override_timestamp(two_days_ago);
        assert!((final_ts - now).num_seconds().abs() < 2);
        assert_eq!(original.unwrap(), two_days_ago);
    }

    #[test]
    fn test_override_timestamp_far_future_is_overridden() {
        let now = Utc::now();
        let two_days_ahead = now + TimeDelta::hours(48);
        let (final_ts, original) = override_timestamp(two_days_ahead);
        assert!((final_ts - now).num_seconds().abs() < 2);
        assert_eq!(original.unwrap(), two_days_ahead);
    }

    #[test]
    fn test_number_value_as_double() {
        use opentelemetry_proto::tonic::metrics::v1::number_data_point::Value;
        assert_eq!(number_value(&Some(Value::AsDouble(3.125))), 3.125);
    }

    #[test]
    fn test_number_value_as_int() {
        use opentelemetry_proto::tonic::metrics::v1::number_data_point::Value;
        assert_eq!(number_value(&Some(Value::AsInt(42))), 42.0);
    }

    #[test]
    fn test_number_value_none() {
        assert_eq!(number_value(&None), 0.0);
    }

    #[test]
    fn test_temporality_str() {
        assert_eq!(temporality_str(1), "delta");
        assert_eq!(temporality_str(2), "cumulative");
        assert_eq!(temporality_str(0), "unspecified");
    }

    // --- Exemplar extraction ---

    use opentelemetry_proto::tonic::metrics::v1::{
        Exemplar, Gauge, Histogram, HistogramDataPoint, Metric, NumberDataPoint,
    };

    const VALID_TRACE_BYTES: [u8; 16] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
    const VALID_SPAN_BYTES: [u8; 8] = [1, 2, 3, 4, 5, 6, 7, 8];

    fn make_exemplar(trace_id: Vec<u8>, span_id: Vec<u8>) -> Exemplar {
        Exemplar {
            filtered_attributes: vec![],
            time_unix_nano: 0,
            value: None,
            span_id,
            trace_id,
        }
    }

    fn build_test_row(exemplars: &[Exemplar]) -> KafkaMetricRow {
        let (row, _) = build_number_row(
            "test.metric",
            "gauge",
            "",
            &HashMap::new(),
            "test-service",
            "test-scope@1.0",
            1_700_000_000_000_000_000,
            0,
            &[],
            1.0,
            None,
            None,
            exemplars,
            0,
        )
        .expect("build_number_row should succeed");
        row
    }

    #[test]
    fn test_exemplar_populates_trace_and_span_ids() {
        let exemplar = make_exemplar(VALID_TRACE_BYTES.to_vec(), VALID_SPAN_BYTES.to_vec());
        let row = build_test_row(&[exemplar]);

        assert_eq!(row.trace_id, BASE64_STANDARD.encode(VALID_TRACE_BYTES));
        assert_eq!(row.span_id, BASE64_STANDARD.encode(VALID_SPAN_BYTES));
    }

    #[test]
    fn test_no_exemplar_yields_empty_ids() {
        let row = build_test_row(&[]);
        assert_eq!(row.trace_id, "");
        assert_eq!(row.span_id, "");
    }

    #[test]
    fn test_first_well_formed_exemplar_is_picked() {
        // First exemplar has an empty trace_id (no context attached) and is skipped;
        // second carries spec-conformant 16-byte bytes and wins.
        let other_trace = [9u8; 16];
        let other_span = [9u8; 8];
        let exemplars = vec![
            make_exemplar(vec![], vec![]),
            make_exemplar(other_trace.to_vec(), other_span.to_vec()),
        ];
        let row = build_test_row(&exemplars);

        assert_eq!(row.trace_id, BASE64_STANDARD.encode(other_trace));
        assert_eq!(row.span_id, BASE64_STANDARD.encode(other_span));
    }

    #[test]
    fn test_malformed_exemplar_before_valid_picks_valid() {
        // A malformed (12-byte) trace_id must not shadow a later well-formed one. Without
        // a length-based filter the malformed entry would be selected and zero-filled by
        // extract_trace_id, silently overwriting real trace context. Regression guard.
        let valid_trace = [7u8; 16];
        let valid_span = [7u8; 8];
        let exemplars = vec![
            make_exemplar(vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], vec![0; 8]),
            make_exemplar(valid_trace.to_vec(), valid_span.to_vec()),
        ];
        let row = build_test_row(&exemplars);

        assert_eq!(row.trace_id, BASE64_STANDARD.encode(valid_trace));
        assert_eq!(row.span_id, BASE64_STANDARD.encode(valid_span));
    }

    #[test]
    fn test_only_malformed_exemplar_yields_empty_ids() {
        // When every exemplar in the vec is malformed, none pass the length filter and
        // the row falls back to empty strings rather than producing an all-zeros sentinel.
        let exemplar = make_exemplar(vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], vec![]);
        let row = build_test_row(&[exemplar]);

        assert_eq!(row.trace_id, "");
        assert_eq!(row.span_id, "");
    }

    #[test]
    fn test_histogram_exemplar_flows_through_pipeline() {
        // Exercises the histogram code path via the public flatten_metric API so a
        // future refactor that splits the histogram path off build_number_row would
        // surface here.
        let exemplar = make_exemplar(VALID_TRACE_BYTES.to_vec(), VALID_SPAN_BYTES.to_vec());
        let metric = Metric {
            name: "test.histogram".to_string(),
            description: String::new(),
            unit: String::new(),
            metadata: vec![],
            data: Some(Data::Histogram(Histogram {
                aggregation_temporality: 2,
                data_points: vec![HistogramDataPoint {
                    attributes: vec![],
                    start_time_unix_nano: 1_700_000_000_000_000_000,
                    time_unix_nano: 1_700_000_000_000_000_000,
                    count: 1,
                    sum: Some(1.0),
                    bucket_counts: vec![1],
                    explicit_bounds: vec![],
                    exemplars: vec![exemplar],
                    flags: 0,
                    min: None,
                    max: None,
                }],
            })),
        };

        let (rows, _) = flatten_metric(metric, None, None).expect("flatten_metric ok");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].trace_id, BASE64_STANDARD.encode(VALID_TRACE_BYTES));
        assert_eq!(rows[0].span_id, BASE64_STANDARD.encode(VALID_SPAN_BYTES));
    }

    #[test]
    fn test_gauge_with_no_exemplar_path_unchanged() {
        // Regression guard: rows without exemplars must still set empty trace/span ids
        // through the public flatten_metric path (the back-compat promise).
        let metric = Metric {
            name: "test.gauge".to_string(),
            description: String::new(),
            unit: String::new(),
            metadata: vec![],
            data: Some(Data::Gauge(Gauge {
                data_points: vec![NumberDataPoint {
                    attributes: vec![],
                    start_time_unix_nano: 1_700_000_000_000_000_000,
                    time_unix_nano: 1_700_000_000_000_000_000,
                    exemplars: vec![],
                    flags: 0,
                    value: None,
                }],
            })),
        };

        let (rows, _) = flatten_metric(metric, None, None).expect("flatten_metric ok");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].trace_id, "");
        assert_eq!(rows[0].span_id, "");
    }

    // --- Series fingerprint ---

    fn attrs(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn test_series_fingerprint_is_order_independent() {
        // The same logical label set must hash identically regardless of HashMap
        // iteration order — this is the invariant the whole join depends on.
        let resource = attrs(&[("k8s.pod", "\"p\""), ("k8s.node", "\"n\"")]);
        let a1 = attrs(&[("topic", "\"t\""), ("partition", "\"9\"")]);
        let a2 = attrs(&[("partition", "\"9\""), ("topic", "\"t\"")]);
        assert_eq!(
            compute_series_fingerprint("m", "gauge", "svc", &resource, &a1),
            compute_series_fingerprint("m", "gauge", "svc", &resource, &a2),
        );
    }

    #[test]
    fn test_series_fingerprint_distinguishes_label_changes() {
        let r = attrs(&[("k8s.pod", "\"p\"")]);
        let base =
            compute_series_fingerprint("m", "gauge", "svc", &r, &attrs(&[("partition", "\"9\"")]));
        // a different value, a different key, a different metric, and a different service
        // each yield a different series
        assert_ne!(
            base,
            compute_series_fingerprint("m", "gauge", "svc", &r, &attrs(&[("partition", "\"10\"")]))
        );
        assert_ne!(
            base,
            compute_series_fingerprint("m", "gauge", "svc", &r, &attrs(&[("part", "\"9\"")]))
        );
        assert_ne!(
            base,
            compute_series_fingerprint("m2", "gauge", "svc", &r, &attrs(&[("partition", "\"9\"")]))
        );
        assert_ne!(
            base,
            compute_series_fingerprint("m", "gauge", "svc2", &r, &attrs(&[("partition", "\"9\"")]))
        );
    }

    #[test]
    fn test_series_fingerprint_no_delimiter_collision() {
        // Length-prefixing must stop {"ab":"c"} from colliding with {"a":"bc"}.
        let r = HashMap::new();
        assert_ne!(
            compute_series_fingerprint("m", "gauge", "", &r, &attrs(&[("ab", "c")])),
            compute_series_fingerprint("m", "gauge", "", &r, &attrs(&[("a", "bc")])),
        );
    }

    #[test]
    fn test_series_fingerprint_distinguishes_metric_type() {
        // A gauge and a sum with the same name and labels are semantically distinct
        // series; metric_series stores metric_type per fingerprint, so they must not
        // collapse onto one deduped row. Regression guard for the type dimension.
        let r = attrs(&[("k8s.pod", "\"p\"")]);
        let a = attrs(&[("partition", "\"9\"")]);
        assert_ne!(
            compute_series_fingerprint("m", "gauge", "svc", &r, &a),
            compute_series_fingerprint("m", "sum", "svc", &r, &a),
        );
    }

    #[test]
    fn test_series_fingerprint_is_pinned() {
        // Golden value: locks the algorithm so an accidental hash-library or
        // canonicalization change is caught (it would silently re-key every series).
        let r = attrs(&[("k8s.pod", "\"p\"")]);
        let a = attrs(&[("topic", "\"t\""), ("partition", "\"9\"")]);
        assert_eq!(
            compute_series_fingerprint("m", "gauge", "svc", &r, &a),
            GOLDEN_FINGERPRINT
        );
    }

    const GOLDEN_FINGERPRINT: i64 = 4834068360040973060;

    #[test]
    fn test_build_row_sets_fingerprint() {
        let row = build_test_row(&[]);
        assert_ne!(
            row.series_fingerprint, 0,
            "every row must carry a series identity"
        );
    }

    fn build_row_at(time_unix_nano: u64) -> (KafkaMetricRow, bool) {
        build_number_row(
            "test.metric",
            "gauge",
            "",
            &HashMap::new(),
            "test-service",
            "test-scope@1.0",
            time_unix_nano,
            0,
            &[],
            1.0,
            None,
            None,
            &[],
            0,
        )
        .expect("build_number_row should succeed")
    }

    #[test]
    fn test_series_fingerprint_ignores_timestamp_override() {
        // $originalTimestamp is a synthetic attribute added only when a point's timestamp
        // falls outside the ±24h window, and it is inserted AFTER the fingerprint is
        // computed. A stale point and a fresh one for the same series must therefore share
        // a fingerprint. Guards the compute-before-insert ordering in build_number_row.
        let fresh_nanos = Utc::now().timestamp_nanos_opt().unwrap() as u64;
        let stale_nanos = (Utc::now() - TimeDelta::hours(48))
            .timestamp_nanos_opt()
            .unwrap() as u64;

        let (fresh, fresh_overridden) = build_row_at(fresh_nanos);
        let (stale, stale_overridden) = build_row_at(stale_nanos);

        // The override must actually fire for the stale point, else the test is vacuous.
        assert!(!fresh_overridden);
        assert!(stale_overridden);
        assert!(!fresh.attributes.contains_key("$originalTimestamp"));
        assert!(stale.attributes.contains_key("$originalTimestamp"));
        // Despite that attribute difference, both map to one series.
        assert_eq!(fresh.series_fingerprint, stale.series_fingerprint);
    }
}
