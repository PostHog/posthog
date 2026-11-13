//! Copies the Kubernetes topology labels of remote-write series onto the OTel
//! resource attributes that the OTLP path sets.
//!
//! The OTel collector's Kubernetes discovery writes `k8s.namespace.name`,
//! `k8s.pod.name` and similar resource attributes. vmagent writes the same facts
//! as the Prometheus labels `namespace`, `pod` and so on. A project that moves
//! from the collector to vmagent keeps its insights working only when both paths
//! carry the same keys, so this step copies each label onto its OTel key. The
//! label stays in `attributes`, as `instance` does for `service.instance.id`.
//!
//! The copy changes the series fingerprint of existing series, so it runs only
//! for the tokens in `REMOTE_WRITE_K8S_RESOURCE_ATTRIBUTE_TOKENS`.

use std::collections::{HashMap, HashSet};

use capture_logs::log_record::ORIGINAL_TIMESTAMP_ATTRIBUTE;
use capture_logs::metric_record::{compute_series_fingerprint, KafkaMetricRow};
use metrics::counter;
use prometheus_rw_proto::prometheus::v1::WriteRequest;

/// Prometheus label -> OTel semantic-convention resource attribute.
const LABEL_TO_RESOURCE_ATTRIBUTE: [(&str, &str); 6] = [
    ("namespace", "k8s.namespace.name"),
    ("pod", "k8s.pod.name"),
    ("node", "k8s.node.name"),
    ("container", "k8s.container.name"),
    ("deployment", "k8s.deployment.name"),
    ("daemonset", "k8s.daemonset.name"),
];

fn resource_key_for(label: &str) -> Option<&'static str> {
    LABEL_TO_RESOURCE_ATTRIBUTE
        .iter()
        .find(|(name, _)| *name == label)
        .map(|(_, key)| *key)
}

/// The row builder adds this attribute per sample after it computes the
/// fingerprint, so the recomputed fingerprint must leave it out too.
const ORIGINAL_TIMESTAMP_ATTRIBUTES: [&str; 2] =
    [ORIGINAL_TIMESTAMP_ATTRIBUTE, "$originalTimestamp"];

/// Attribute values are JSON-encoded strings, so an empty label is `""`.
const EMPTY_JSON_STRING: &str = "\"\"";

/// Length of `value` as the row builder stores it: a JSON string, quotes and
/// escapes included. A control character escapes to six bytes, so the raw
/// length would undercount a crafted label by up to six times.
fn json_string_len(value: &str) -> usize {
    let escaped: usize = value
        .chars()
        .map(|c| match c {
            '"' | '\\' | '\u{08}' | '\u{0c}' | '\n' | '\r' | '\t' => 2,
            c if (c as u32) < 0x20 => 6,
            c => c.len_utf8(),
        })
        .sum();
    escaped + 2
}

pub struct K8sResourceAttributes {
    tokens: HashSet<String>,
}

impl K8sResourceAttributes {
    /// Parses a comma-separated token list. Blank entries are ignored, so an
    /// unset or empty variable turns the step off.
    pub fn from_token_list(tokens: &str) -> Self {
        Self {
            tokens: tokens
                .split(',')
                .map(str::trim)
                .filter(|token| !token.is_empty())
                .map(str::to_string)
                .collect(),
        }
    }

    pub fn is_enabled_for(&self, token: &str) -> bool {
        self.tokens.contains(token)
    }

    /// Bytes that `apply` adds to the rows of this request. The handler adds it
    /// to the expansion estimate, because `apply` clones each copied label into
    /// every row after that check, and a large label would otherwise slip past
    /// the memory guard.
    pub fn estimate_added_bytes(&self, token: &str, request: &WriteRequest) -> u64 {
        if !self.is_enabled_for(token) {
            return 0;
        }
        request
            .timeseries
            .iter()
            .map(|series| {
                let per_row: u64 = series
                    .labels
                    .iter()
                    .filter(|label| !label.value.is_empty())
                    .filter_map(|label| resource_key_for(&label.name).map(|key| (key, label)))
                    .map(|(key, label)| (key.len() + json_string_len(&label.value)) as u64)
                    .sum();
                per_row * series.samples.len() as u64
            })
            .sum()
    }

    pub fn apply(&self, token: &str, rows: &mut [KafkaMetricRow]) {
        if !self.is_enabled_for(token) {
            return;
        }

        // Rows of one series share labels, so each fingerprint maps to one new value.
        let mut recomputed: HashMap<i64, i64> = HashMap::new();
        let mut copied = 0u64;

        for row in rows.iter_mut() {
            let mut changed = false;
            for (label, resource_key) in LABEL_TO_RESOURCE_ATTRIBUTE {
                // An explicit resource attribute wins over the label.
                if row.resource_attributes.contains_key(resource_key) {
                    continue;
                }
                let Some(value) = row.attributes.get(label) else {
                    continue;
                };
                if value == EMPTY_JSON_STRING {
                    continue;
                }
                let key = resource_key.to_string();
                row.resource_attributes.insert(key, value.clone());
                changed = true;
            }
            if !changed {
                continue;
            }
            copied += 1;

            let fingerprint = match recomputed.get(&row.series_fingerprint) {
                Some(fingerprint) => *fingerprint,
                None => {
                    let mut series_attributes = row.attributes.clone();
                    for attribute in ORIGINAL_TIMESTAMP_ATTRIBUTES {
                        series_attributes.remove(attribute);
                    }
                    let fingerprint = compute_series_fingerprint(
                        &row.metric_name,
                        &row.metric_type,
                        &row.service_name,
                        &row.resource_attributes,
                        &series_attributes,
                    );
                    recomputed.insert(row.series_fingerprint, fingerprint);
                    fingerprint
                }
            };
            row.series_fingerprint = fingerprint;
        }

        if copied > 0 {
            counter!("capture_metrics_remote_write_k8s_resource_attributes_copied")
                .increment(copied);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use capture_logs::endpoints::prometheus::write_timeseries_to_kafka_rows;
    use chrono::Utc;
    use prometheus_rw_proto::prometheus::v1::{Label, Sample, TimeSeries};

    const TOKEN: &str = "phc_internal";

    const POD_SERIES: [(&str, &str); 6] = [
        ("__name__", "capture_kafka_producer_queue_depth"),
        ("job", "kubernetes-pods"),
        ("instance", "10.0.0.1:8000"),
        ("namespace", "capture"),
        ("pod", "capture-abc"),
        ("node", ""),
    ];

    fn label(name: &str, value: &str) -> Label {
        Label {
            name: name.to_string(),
            value: value.to_string(),
        }
    }

    fn sample(value: f64) -> Sample {
        Sample {
            value,
            timestamp: Utc::now().timestamp_millis(),
        }
    }

    /// Two samples of one series, built by the real remote-write row builder.
    fn pod_rows() -> Vec<KafkaMetricRow> {
        let series = TimeSeries {
            labels: POD_SERIES.iter().map(|(n, v)| label(n, v)).collect(),
            samples: vec![sample(1.0), sample(2.0)],
        };
        write_timeseries_to_kafka_rows(vec![series], &[]).0
    }

    fn resource<'a>(row: &'a KafkaMetricRow, key: &str) -> Option<&'a str> {
        row.resource_attributes.get(key).map(String::as_str)
    }

    fn step(tokens: &str) -> K8sResourceAttributes {
        K8sResourceAttributes::from_token_list(tokens)
    }

    #[test]
    fn copies_labels_for_listed_tokens() {
        let mut rows = pod_rows();
        step(&format!(" other ,{TOKEN}")).apply(TOKEN, &mut rows);

        for row in &rows {
            let namespace = resource(row, "k8s.namespace.name");
            assert_eq!(namespace, Some("\"capture\""));
            let pod = resource(row, "k8s.pod.name");
            assert_eq!(pod, Some("\"capture-abc\""));
            // An empty label does not become an attribute.
            assert_eq!(resource(row, "k8s.node.name"), None);
            // The label stays queryable under its Prometheus name.
            assert!(row.attributes.contains_key("namespace"));
        }
    }

    #[test]
    fn recomputes_one_fingerprint_per_series() {
        let original = pod_rows();
        let mut rows = pod_rows();
        step(TOKEN).apply(TOKEN, &mut rows);

        let row = &rows[0];
        let expected = compute_series_fingerprint(
            &row.metric_name,
            &row.metric_type,
            &row.service_name,
            &row.resource_attributes,
            &row.attributes,
        );
        assert_ne!(row.series_fingerprint, original[0].series_fingerprint);
        assert_eq!(row.series_fingerprint, expected);
        assert_eq!(rows[1].series_fingerprint, expected);
    }

    #[test]
    fn leaves_other_tokens_unchanged() {
        let original = pod_rows();
        let mut rows = pod_rows();
        step(TOKEN).apply("phc_customer", &mut rows);
        step("").apply(TOKEN, &mut rows);

        let (row, before) = (&rows[0], &original[0]);
        assert_eq!(row.resource_attributes, before.resource_attributes);
        assert_eq!(row.series_fingerprint, before.series_fingerprint);
    }

    #[test]
    fn estimates_the_bytes_the_copy_adds() {
        let series = TimeSeries {
            labels: POD_SERIES.iter().map(|(n, v)| label(n, v)).collect(),
            samples: vec![sample(1.0), sample(2.0), sample(3.0)],
        };
        let request = WriteRequest {
            timeseries: vec![series],
            metadata: vec![],
        };

        // k8s.namespace.name + "capture" and k8s.pod.name + "capture-abc",
        // each value with its JSON quotes. The empty node label adds nothing.
        let per_row = (18 + 7 + 2) + (12 + 11 + 2);
        let added = step(TOKEN).estimate_added_bytes(TOKEN, &request);
        assert_eq!(added, 3 * per_row);
        let other = step(TOKEN).estimate_added_bytes("phc_customer", &request);
        assert_eq!(other, 0);
    }

    #[test]
    fn json_string_len_matches_the_encoded_value() {
        for value in [
            "capture-abc",
            "",
            "a\"b\\c",
            "\n\t\u{08}\u{0c}\r",
            "\u{01}\u{1f}",
            "pod-é-\u{7f}",
        ] {
            assert_eq!(
                json_string_len(value),
                serde_json::json!(value).to_string().len(),
                "{value:?}"
            );
        }
    }

    #[test]
    fn keeps_an_existing_resource_attribute() {
        let mut rows = pod_rows();
        for row in rows.iter_mut() {
            let key = "k8s.namespace.name".to_string();
            row.resource_attributes.insert(key, "\"explicit\"".into());
        }
        step(TOKEN).apply(TOKEN, &mut rows);

        let namespace = resource(&rows[0], "k8s.namespace.name");
        assert_eq!(namespace, Some("\"explicit\""));
        let pod = resource(&rows[0], "k8s.pod.name");
        assert_eq!(pod, Some("\"capture-abc\""));
    }
}
