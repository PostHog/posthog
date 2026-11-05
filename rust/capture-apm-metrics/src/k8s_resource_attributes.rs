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

use capture_logs::metric_record::{compute_series_fingerprint, KafkaMetricRow};
use metrics::counter;

/// Prometheus label -> OTel semantic-convention resource attribute.
const LABEL_TO_RESOURCE_ATTRIBUTE: [(&str, &str); 6] = [
    ("namespace", "k8s.namespace.name"),
    ("pod", "k8s.pod.name"),
    ("node", "k8s.node.name"),
    ("container", "k8s.container.name"),
    ("deployment", "k8s.deployment.name"),
    ("daemonset", "k8s.daemonset.name"),
];

/// The row builder adds this attribute per sample after it computes the
/// fingerprint, so the recomputed fingerprint must leave it out too.
const ORIGINAL_TIMESTAMP_ATTRIBUTE: &str = "$originalTimestamp";

/// Attribute values are JSON-encoded strings, so an empty label is `""`.
const EMPTY_JSON_STRING: &str = "\"\"";

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
                row.resource_attributes
                    .insert(resource_key.to_string(), value.clone());
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
                    series_attributes.remove(ORIGINAL_TIMESTAMP_ATTRIBUTE);
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
    use prometheus_rw_proto::prometheus::v1::{Label, Sample, TimeSeries};

    const TOKEN: &str = "phc_internal";

    fn series(labels: &[(&str, &str)]) -> TimeSeries {
        TimeSeries {
            labels: labels
                .iter()
                .map(|(name, value)| Label {
                    name: name.to_string(),
                    value: value.to_string(),
                })
                .collect(),
            samples: vec![
                Sample {
                    value: 1.0,
                    timestamp: chrono::Utc::now().timestamp_millis(),
                },
                Sample {
                    value: 2.0,
                    timestamp: chrono::Utc::now().timestamp_millis(),
                },
            ],
        }
    }

    fn rows(labels: &[(&str, &str)]) -> Vec<KafkaMetricRow> {
        write_timeseries_to_kafka_rows(vec![series(labels)], &[]).0
    }

    const POD_SERIES: [(&str, &str); 6] = [
        ("__name__", "capture_kafka_producer_queue_depth"),
        ("job", "kubernetes-pods"),
        ("instance", "10.0.0.1:8000"),
        ("namespace", "capture"),
        ("pod", "capture-abc"),
        ("node", ""),
    ];

    #[test]
    fn copies_labels_to_resource_attributes_for_listed_tokens() {
        let mut rows = rows(&POD_SERIES);
        K8sResourceAttributes::from_token_list(&format!(" other ,{TOKEN}"))
            .apply(TOKEN, &mut rows);

        for row in &rows {
            assert_eq!(
                row.resource_attributes.get("k8s.namespace.name").unwrap(),
                "\"capture\""
            );
            assert_eq!(
                row.resource_attributes.get("k8s.pod.name").unwrap(),
                "\"capture-abc\""
            );
            // An empty label does not become an attribute.
            assert!(!row.resource_attributes.contains_key("k8s.node.name"));
            // The label stays queryable under its Prometheus name.
            assert_eq!(row.attributes.get("namespace").unwrap(), "\"capture\"");
        }
    }

    #[test]
    fn recomputes_one_fingerprint_per_series() {
        let original = rows(&POD_SERIES);
        let mut copied = rows(&POD_SERIES);
        K8sResourceAttributes::from_token_list(TOKEN).apply(TOKEN, &mut copied);

        assert_ne!(copied[0].series_fingerprint, original[0].series_fingerprint);
        assert_eq!(copied[0].series_fingerprint, copied[1].series_fingerprint);
        assert_eq!(
            copied[0].series_fingerprint,
            compute_series_fingerprint(
                &copied[0].metric_name,
                &copied[0].metric_type,
                &copied[0].service_name,
                &copied[0].resource_attributes,
                &copied[0].attributes,
            )
        );
    }

    #[test]
    fn leaves_other_tokens_unchanged() {
        let original = rows(&POD_SERIES);
        let mut untouched = rows(&POD_SERIES);
        K8sResourceAttributes::from_token_list(TOKEN).apply("phc_customer", &mut untouched);
        K8sResourceAttributes::from_token_list("").apply(TOKEN, &mut untouched);

        assert_eq!(
            untouched[0].resource_attributes,
            original[0].resource_attributes
        );
        assert_eq!(
            untouched[0].series_fingerprint,
            original[0].series_fingerprint
        );
    }

    #[test]
    fn keeps_an_existing_resource_attribute() {
        let mut rows = rows(&POD_SERIES);
        for row in rows.iter_mut() {
            row.resource_attributes
                .insert("k8s.namespace.name".into(), "\"explicit\"".into());
        }
        K8sResourceAttributes::from_token_list(TOKEN).apply(TOKEN, &mut rows);

        assert_eq!(
            rows[0].resource_attributes.get("k8s.namespace.name").unwrap(),
            "\"explicit\""
        );
        assert_eq!(
            rows[0].resource_attributes.get("k8s.pod.name").unwrap(),
            "\"capture-abc\""
        );
    }
}
