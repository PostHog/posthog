//! Port of `otlp-payload.ts`: a hand-built OTLP/JSON `ExportMetricsServiceRequest`.
//!
//! The result is a `JsValue` with the TypeScript key order, so `json_stringify` gives the
//! bytes that Node sends.

use super::compile::{starts_with, CompiledMetricRule};
use super::ordered::InsertionMap;
use super::tally::{
    BatchTallies, LabelValue, MetricTallyEntry, DEFAULT_HISTOGRAM_BOUNDS, SPAN_VALUE_DURATION_MS,
};
use crate::js::{JsObject, JsString, JsValue};

const SCOPE_NAME: &str = "posthog/logs-metric-rules";

const TIME_BUCKET_MS: f64 = 10_000.0;

const OTLP_TEMPORALITY_DELTA: f64 = 1.0;

const ATTRIBUTE_PREFIXES: [&str; 2] = ["attributes.", "resource_attributes."];

fn object(entries: Vec<(&str, JsValue)>) -> JsValue {
    let mut o = JsObject::new();
    for (k, v) in entries {
        o.insert_str(k, v);
    }
    JsValue::Object(o)
}

fn string_attribute(key: JsString, value: JsString) -> JsValue {
    let mut o = JsObject::new();
    o.insert_str("key", JsValue::String(key));
    o.insert_str(
        "value",
        object(vec![("stringValue", JsValue::String(value))]),
    );
    JsValue::Object(o)
}

/// `{ key, value: { stringValue } }`. `JSON.stringify` omits a function-valued property.
fn label_attribute(key: JsString, value: &LabelValue) -> JsValue {
    let mut inner = JsObject::new();
    if let Some(v) = value.to_json() {
        inner.insert_str("stringValue", v);
    }
    let mut o = JsObject::new();
    o.insert_str("key", JsValue::String(key));
    o.insert_str("value", JsValue::Object(inner));
    JsValue::Object(o)
}

/// The OTel SDK attribute for the series past a cardinality limit.
fn overflow_attribute() -> JsValue {
    object(vec![
        ("key", JsValue::string("otel.metric.overflow")),
        ("value", object(vec![("boolValue", JsValue::Bool(true))])),
    ])
}

/// Series identity has no bucket bounds, so each bucket layout gets its own series.
fn bucket_layout_attribute() -> JsValue {
    string_attribute(
        JsString::from("posthog.bucket_layout"),
        JsString::from("otel_default_v1"),
    )
}

fn label_name(group_by_key: &JsString) -> JsString {
    for prefix in ATTRIBUTE_PREFIXES {
        if starts_with(group_by_key, prefix) {
            return group_by_key.utf16_slice(prefix.len(), group_by_key.utf16_len());
        }
    }
    group_by_key.clone()
}

/// `BigInt(Math.floor(nowMs / 10000) * 10000) * 1_000_000n`.
fn snap_to_bucket_nanos(now_ms: f64) -> i128 {
    ((now_ms / TIME_BUCKET_MS).floor() * TIME_BUCKET_MS) as i128 * 1_000_000
}

struct RulePoints<'a> {
    rule: &'a CompiledMetricRule,
    entries: Vec<&'a MetricTallyEntry>,
}

pub fn build_metric_rules_otlp_payload(
    rules: &[CompiledMetricRule],
    tallies: &BatchTallies,
    now_ms: f64,
) -> Option<JsValue> {
    let mut by_service: Vec<(JsString, InsertionMap<RulePoints<'_>>)> = Vec::new();
    for rule in rules {
        let Some(rule_tallies) = tallies.by_rule.get(&rule.id) else {
            continue;
        };
        let service_index = rule.group_by.iter().position(|k| *k == "service_name");
        for entry in rule_tallies.values() {
            let service = match service_index {
                // The service label comes from the `service_name` column, so it is a string.
                Some(i) if !entry.overflow => entry
                    .label_values
                    .get(i)
                    .and_then(LabelValue::as_js_string)
                    .cloned()
                    .unwrap_or_default(),
                _ => JsString::new(),
            };
            let slot = match by_service.iter().position(|(s, _)| *s == service) {
                Some(i) => i,
                None => {
                    by_service.push((service, InsertionMap::new()));
                    by_service.len() - 1
                }
            };
            let points = by_service[slot]
                .1
                .get_or_insert_with(&rule.id, || RulePoints {
                    rule,
                    entries: Vec::new(),
                });
            points.entries.push(entry);
        }
    }
    if by_service.is_empty() {
        return None;
    }

    let time_nanos = snap_to_bucket_nanos(now_ms);
    let time_unix_nano = JsString::from(time_nanos.to_string());
    let start_time_unix_nano =
        JsString::from((time_nanos - TIME_BUCKET_MS as i128 * 1_000_000).to_string());

    let resource_metrics = by_service
        .iter()
        .map(|(service, rule_map)| {
            let attributes = if service.is_empty() {
                vec![]
            } else {
                vec![string_attribute(
                    JsString::from("service.name"),
                    service.clone(),
                )]
            };
            let metrics = rule_map
                .values()
                .map(|points| {
                    serialize_rule_metric(
                        points.rule,
                        &points.entries,
                        &start_time_unix_nano,
                        &time_unix_nano,
                    )
                })
                .collect();
            object(vec![
                (
                    "resource",
                    object(vec![("attributes", JsValue::Array(attributes))]),
                ),
                (
                    "scopeMetrics",
                    JsValue::Array(vec![object(vec![
                        ("scope", object(vec![("name", JsValue::string(SCOPE_NAME))])),
                        ("metrics", JsValue::Array(metrics)),
                    ])]),
                ),
            ])
        })
        .collect();

    Some(object(vec![(
        "resourceMetrics",
        JsValue::Array(resource_metrics),
    )]))
}

fn number(n: f64) -> JsValue {
    JsValue::Number(n)
}

fn serialize_rule_metric(
    rule: &CompiledMetricRule,
    entries: &[&MetricTallyEntry],
    start_time_unix_nano: &JsString,
    time_unix_nano: &JsString,
) -> JsValue {
    let mut metric = JsObject::new();
    metric.insert_str("name", JsValue::String(rule.metric_name.clone()));
    if let Some(value_attribute) = &rule.value_attribute {
        if *value_attribute == SPAN_VALUE_DURATION_MS {
            metric.insert_str("unit", JsValue::string("ms"));
        }
        let data_points = entries
            .iter()
            .map(|entry| {
                let mut point = data_point_base(
                    rule,
                    entry,
                    start_time_unix_nano,
                    time_unix_nano,
                    Some(bucket_layout_attribute()),
                );
                point.insert_str("count", number(entry.count as f64));
                point.insert_str("sum", number(entry.sum));
                let buckets = match &entry.bucket_counts {
                    Some(b) => JsValue::Array(b.iter().map(|c| number(*c as f64)).collect()),
                    None => JsValue::Null,
                };
                point.insert_str("bucketCounts", buckets);
                point.insert_str(
                    "explicitBounds",
                    JsValue::Array(
                        DEFAULT_HISTOGRAM_BOUNDS
                            .iter()
                            .map(|b| number(*b))
                            .collect(),
                    ),
                );
                JsValue::Object(point)
            })
            .collect();
        metric.insert_str(
            "histogram",
            object(vec![
                ("dataPoints", JsValue::Array(data_points)),
                ("aggregationTemporality", number(OTLP_TEMPORALITY_DELTA)),
            ]),
        );
    } else {
        let data_points = entries
            .iter()
            .map(|entry| {
                let mut point =
                    data_point_base(rule, entry, start_time_unix_nano, time_unix_nano, None);
                point.insert_str("asDouble", number(entry.count as f64));
                JsValue::Object(point)
            })
            .collect();
        metric.insert_str(
            "sum",
            object(vec![
                ("dataPoints", JsValue::Array(data_points)),
                ("aggregationTemporality", number(OTLP_TEMPORALITY_DELTA)),
                ("isMonotonic", JsValue::Bool(true)),
            ]),
        );
    }
    JsValue::Object(metric)
}

fn data_point_base(
    rule: &CompiledMetricRule,
    entry: &MetricTallyEntry,
    start_time_unix_nano: &JsString,
    time_unix_nano: &JsString,
    extra_attribute: Option<JsValue>,
) -> JsObject {
    let mut attributes = Vec::new();
    if entry.overflow {
        attributes.push(overflow_attribute());
    }
    attributes.extend(extra_attribute);
    if !entry.overflow {
        for (i, key) in rule.group_by.iter().enumerate() {
            // `service_name` is on the resource block instead.
            if *key == "service_name" {
                continue;
            }
            let value = entry
                .label_values
                .get(i)
                .cloned()
                .unwrap_or_else(LabelValue::empty);
            attributes.push(label_attribute(label_name(key), &value));
        }
    }
    let mut point = JsObject::new();
    point.insert_str("attributes", JsValue::Array(attributes));
    point.insert_str(
        "startTimeUnixNano",
        JsValue::String(start_time_unix_nano.clone()),
    );
    point.insert_str("timeUnixNano", JsValue::String(time_unix_nano.clone()));
    if let Some(trace_id) = &entry.exemplar_trace_id {
        let as_double = if rule.value_attribute.is_some() {
            entry.sum
        } else {
            entry.count as f64
        };
        let mut exemplar = JsObject::new();
        exemplar.insert_str("filteredAttributes", JsValue::Array(vec![]));
        exemplar.insert_str("timeUnixNano", JsValue::String(time_unix_nano.clone()));
        exemplar.insert_str("asDouble", number(as_double));
        exemplar.insert_str("traceId", JsValue::string(trace_id));
        if let Some(span_id) = &entry.exemplar_span_id {
            exemplar.insert_str("spanId", JsValue::string(span_id));
        }
        point.insert_str("exemplars", JsValue::Array(vec![JsValue::Object(exemplar)]));
    }
    point
}
