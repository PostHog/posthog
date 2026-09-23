//! Converts component rows of a classic Prometheus histogram (`_bucket`,
//! `_count`, `_sum`) to one native histogram row. The remote-write code calls
//! this module after `capture-logs` builds the rows and before the series label
//! gate.
//!
//! The module converts a histogram only when one request has its `_sum` series
//! and `+Inf` bucket for the same label set and timestamp. Bucket values must
//! be consistent. Other component rows stay unchanged. This preserves data
//! when a sender divides a histogram across requests. Query code must combine
//! native and normal rows by label set.
//!
//! The module converts `le` and `quantile` label values to Go's shortest float
//! format. Therefore, `le="1.0"` and `le="1"` identify the same series.

use std::collections::HashMap;

use capture_logs::metric_record::{compute_series_fingerprint, KafkaMetricRow};
use chrono::{DateTime, Utc};
use metrics::counter;
use prometheus_rw_proto::prometheus::v1::{metric_metadata::MetricType, MetricMetadata};
use serde_json::json;
use uuid::Uuid;

const LE_LABEL: &str = "le";
const QUANTILE_LABEL: &str = "quantile";
const ORIGINAL_TIMESTAMP_LABEL: &str = "$originalTimestamp";
const BUCKET_SUFFIX: &str = "_bucket";
const COUNT_SUFFIX: &str = "_count";
const SUM_SUFFIX: &str = "_sum";
const SUM_TYPE: &str = "sum";
const HISTOGRAM_TYPE: &str = "histogram";

/// Converts `le` and `quantile` labels, then converts complete classic
/// histograms to native rows. Native rows come first. Other rows keep their
/// original order.
pub fn fold_classic_histograms(
    mut rows: Vec<KafkaMetricRow>,
    metadata: &[MetricMetadata],
) -> Vec<KafkaMetricRow> {
    normalize_float_labels(&mut rows);
    let declared: HashMap<&str, MetricType> = metadata
        .iter()
        .filter_map(|m| {
            MetricType::try_from(m.r#type)
                .ok()
                .map(|t| (m.metric_family_name.as_str(), t))
        })
        .collect();

    let mut groups: HashMap<HistogramKey, HistogramParts> = HashMap::new();
    let mut order: Vec<HistogramKey> = Vec::new();
    let mut component_rows = 0u64;
    for (index, row) in rows.iter().enumerate() {
        let Some((base_name, component)) = histogram_component(row, &declared) else {
            continue;
        };
        component_rows += 1;
        let skip = matches!(component, HistogramComponent::Bucket(_)).then_some(LE_LABEL);
        let key = HistogramKey {
            base_name,
            service_name: row.service_name.clone(),
            resource_attributes: sorted_pairs(&row.resource_attributes, None),
            attributes: sorted_pairs(&row.attributes, skip),
            timestamp: row.timestamp,
        };
        if !groups.contains_key(&key) {
            order.push(key.clone());
        }
        let parts = groups.entry(key).or_default();
        match component {
            HistogramComponent::Bucket(le) => parts.buckets.push((le, row.value, index)),
            HistogramComponent::Count => parts.counts.push((row.value, index)),
            HistogramComponent::Sum => parts.sums.push((row.value, index)),
        }
    }

    let mut consumed = vec![false; rows.len()];
    let mut folded = Vec::new();
    for key in order {
        let parts = &groups[&key];
        let Some(histogram) = assemble_histogram(parts) else {
            continue;
        };
        let Some((_, sum_index)) = parts.sums.last() else {
            continue;
        };
        for (_, _, index) in &parts.buckets {
            consumed[*index] = true;
        }
        for (_, index) in parts.counts.iter().chain(&parts.sums) {
            consumed[*index] = true;
        }
        let sum_row = &rows[*sum_index];
        let resource_attributes: HashMap<String, String> =
            key.resource_attributes.iter().cloned().collect();
        let attributes: HashMap<String, String> = key.attributes.iter().cloned().collect();
        let series_fingerprint = compute_series_fingerprint(
            &key.base_name,
            HISTOGRAM_TYPE,
            &key.service_name,
            &resource_attributes,
            &attributes,
        );
        folded.push(KafkaMetricRow {
            uuid: Uuid::now_v7().to_string(),
            trace_id: String::new(),
            span_id: String::new(),
            trace_flags: 0,
            timestamp: key.timestamp,
            observed_timestamp: sum_row.observed_timestamp,
            service_name: key.service_name,
            metric_name: key.base_name,
            metric_type: HISTOGRAM_TYPE.to_string(),
            value: histogram.sum,
            count: histogram.total,
            histogram_bounds: histogram.bounds,
            histogram_counts: histogram.counts,
            unit: sum_row.unit.clone(),
            aggregation_temporality: "cumulative".to_string(),
            is_monotonic: false,
            resource_attributes,
            instrumentation_scope: String::new(),
            attributes,
            series_fingerprint,
            has_labels: true,
            retention_days: sum_row.retention_days,
        });
    }

    let folded_rows = consumed.iter().filter(|consumed| **consumed).count() as u64;
    if !folded.is_empty() {
        counter!("capture_metrics_remote_write_histograms_assembled")
            .increment(folded.len() as u64);
        counter!("capture_metrics_remote_write_histogram_samples_folded").increment(folded_rows);
    }
    if component_rows > folded_rows {
        counter!("capture_metrics_remote_write_histogram_components_passed_through")
            .increment(component_rows - folded_rows);
    }

    folded.extend(
        rows.into_iter()
            .zip(consumed)
            .filter_map(|(row, is_consumed)| (!is_consumed).then_some(row)),
    );
    folded
}

fn normalize_float_labels(rows: &mut [KafkaMetricRow]) {
    for row in rows {
        let mut changed = false;
        for label in [LE_LABEL, QUANTILE_LABEL] {
            let Some(value) = row.attributes.get_mut(label) else {
                continue;
            };
            let Ok(decoded) = serde_json::from_str::<String>(value) else {
                continue;
            };
            let normalized = normalize_float_label(&decoded);
            if normalized != decoded {
                *value = json!(normalized).to_string();
                changed = true;
            }
        }
        if changed {
            let mut attributes = row.attributes.clone();
            attributes.remove(ORIGINAL_TIMESTAMP_LABEL);
            row.series_fingerprint = compute_series_fingerprint(
                &row.metric_name,
                &row.metric_type,
                &row.service_name,
                &row.resource_attributes,
                &attributes,
            );
        }
    }
}

/// Formats a float as Go's `strconv.FormatFloat(v, 'g', -1, 64)` does.
/// Returns an unparseable value unchanged.
pub fn normalize_float_label(value: &str) -> String {
    let Ok(parsed) = value.trim().parse::<f64>() else {
        return value.to_string();
    };
    format_float_shortest(parsed)
}

fn format_float_shortest(value: f64) -> String {
    if value.is_nan() {
        return "NaN".to_string();
    }
    if value.is_infinite() {
        return if value > 0.0 { "+Inf" } else { "-Inf" }.to_string();
    }
    if value == 0.0 {
        return if value.is_sign_negative() { "-0" } else { "0" }.to_string();
    }
    let scientific = format!("{value:e}");
    let (mantissa, exponent) = scientific
        .split_once('e')
        .unwrap_or((scientific.as_str(), "0"));
    let exponent: i32 = exponent.parse().unwrap_or(0);
    if !(-4..=5).contains(&exponent) {
        let sign = if exponent < 0 { '-' } else { '+' };
        return format!("{mantissa}e{sign}{:02}", exponent.abs());
    }
    format!("{value}")
}

#[derive(Clone, Copy)]
enum HistogramComponent {
    Bucket(f64),
    Count,
    Sum,
}

fn histogram_component(
    row: &KafkaMetricRow,
    declared: &HashMap<&str, MetricType>,
) -> Option<(String, HistogramComponent)> {
    if row.metric_type != SUM_TYPE || row.attributes.contains_key(ORIGINAL_TIMESTAMP_LABEL) {
        return None;
    }
    let name = row.metric_name.as_str();
    let (base, component) = if let Some(base) = name.strip_suffix(BUCKET_SUFFIX) {
        let le: String = serde_json::from_str(row.attributes.get(LE_LABEL)?).ok()?;
        (base, HistogramComponent::Bucket(le.parse::<f64>().ok()?))
    } else if let Some(base) = name.strip_suffix(COUNT_SUFFIX) {
        (base, HistogramComponent::Count)
    } else {
        (name.strip_suffix(SUM_SUFFIX)?, HistogramComponent::Sum)
    };
    if base.is_empty() {
        return None;
    }
    match declared.get(base) {
        None | Some(MetricType::Histogram) => Some((base.to_string(), component)),
        Some(_) => None,
    }
}

#[derive(Clone, Hash, PartialEq, Eq)]
struct HistogramKey {
    base_name: String,
    service_name: String,
    resource_attributes: Vec<(String, String)>,
    attributes: Vec<(String, String)>,
    timestamp: DateTime<Utc>,
}

#[derive(Default)]
struct HistogramParts {
    buckets: Vec<(f64, f64, usize)>,
    counts: Vec<(f64, usize)>,
    sums: Vec<(f64, usize)>,
}

struct AssembledHistogram {
    bounds: Vec<f64>,
    counts: Vec<i64>,
    total: i64,
    sum: f64,
}

fn sorted_pairs(map: &HashMap<String, String>, skip: Option<&str>) -> Vec<(String, String)> {
    let mut pairs: Vec<(String, String)> = map
        .iter()
        .filter(|(key, _)| Some(key.as_str()) != skip)
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect();
    pairs.sort_unstable();
    pairs
}

/// A histogram is converted only when it has `_sum` and `+Inf` bucket values.
/// Bucket values must be non-negative integers that do not decrease. A present
/// `_count` value must equal the `+Inf` bucket value.
fn assemble_histogram(parts: &HistogramParts) -> Option<AssembledHistogram> {
    let (sum, _) = *parts.sums.last()?;
    if parts.sums.iter().any(|(value, _)| *value != sum) {
        return None;
    }
    let mut buckets: Vec<(f64, f64)> = parts
        .buckets
        .iter()
        .map(|(le, value, _)| (*le, *value))
        .collect();
    if buckets.iter().any(|(le, _)| le.is_nan()) {
        return None;
    }
    buckets.sort_by(|a, b| a.0.total_cmp(&b.0));
    buckets.dedup_by(|a, b| a.0 == b.0 && a.1 == b.1);
    if buckets.windows(2).any(|pair| pair[0].0 == pair[1].0) {
        return None;
    }
    let (last_le, total_value) = *buckets.last()?;
    if !(last_le.is_infinite() && last_le > 0.0) {
        return None;
    }
    if parts.counts.iter().any(|(count, _)| *count != total_value) {
        return None;
    }
    let total = integral_count(total_value)?;
    let mut bounds = Vec::with_capacity(buckets.len() - 1);
    let mut counts = Vec::with_capacity(buckets.len());
    let mut previous = 0i64;
    for (le, value) in &buckets[..buckets.len() - 1] {
        if le.is_infinite() {
            return None;
        }
        let cumulative = integral_count(*value)?;
        if cumulative < previous {
            return None;
        }
        bounds.push(*le);
        counts.push(cumulative - previous);
        previous = cumulative;
    }
    if total < previous {
        return None;
    }
    counts.push(total - previous);
    Some(AssembledHistogram {
        bounds,
        counts,
        total,
        sum,
    })
}

fn integral_count(value: f64) -> Option<i64> {
    if !value.is_finite() || value < 0.0 || value.fract() != 0.0 || value > i64::MAX as f64 {
        return None;
    }
    Some(value as i64)
}
