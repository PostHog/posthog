use std::collections::HashMap;

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
use tracing::debug;
use uuid::Uuid;

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
    _exemplars: &[opentelemetry_proto::tonic::metrics::v1::Exemplar],
    flags: u32,
) -> Result<(KafkaMetricRow, bool)> {
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

    if let Some(original) = original_timestamp {
        attributes.insert("$originalTimestamp".to_string(), original.to_rfc3339());
    }

    let observed_timestamp = Utc::now();

    let row = KafkaMetricRow {
        uuid: Uuid::now_v7().to_string(),
        trace_id: String::new(),
        span_id: String::new(),
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
    };

    Ok((row, was_overridden))
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
}
