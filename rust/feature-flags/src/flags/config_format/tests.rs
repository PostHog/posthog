use super::*;
use crate::flags::cache_builder::{
    compute_flag_dependencies, extract_cohort_ids_from_flag_filters,
};
use crate::flags::feature_flag_list::PreparedFlags;
use crate::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, HypercacheFlagsWrapper, PreparedFlagDefinitions,
};
use serde_json::json;
use std::sync::Arc;

fn flag(filters: Value) -> Value {
    json!({"id": 1, "team_id": 1, "key": "example", "active": true, "version": 2, "filters": filters})
}

#[test]
fn v1_cache_round_trip_preserves_discriminator_and_unknown_fields() {
    for version in [None, Some(json!(1)), Some(json!(1.0))] {
        let mut filters = json!({
            "groups": [{"aggregation_group_type_index": null, "extra_group": [1],
                "properties": [{"key": "email", "type": "person", "value": "example.com", "operator": null, "negation": null, "group_type_index": null, "extra_property": true}]}],
            "multivariate": {"extra_options": true, "variants": [{"key": "control", "name": null, "rollout_percentage": 100.0, "extra_variant": [2]}]},
            "extra_top": {"nested": [null, false]}
        });
        if let Some(version) = version {
            filters["version"] = version;
        }
        let decoded: FeatureFlag = serde_json::from_value(flag(filters.clone())).unwrap();
        assert!(decoded.filters.is_v1());
        assert_eq!(serde_json::to_value(&decoded).unwrap()["filters"], filters);
        assert_eq!(decoded.version, Some(2));
    }
}

#[test]
fn non_v1_cache_documents_remain_opaque_and_keep_healthy_siblings() {
    for version in [
        json!(2),
        json!(2.0),
        json!(3),
        json!(1.5),
        json!("1"),
        json!("2"),
        json!(true),
        json!(false),
        Value::Null,
    ] {
        for groups in [
            json!("not v1 groups"),
            json!([{"properties": [{"type": "cohort", "key": "id", "value": 42}, {"type": "flag", "key": "999", "value": true}]}]),
        ] {
            let filters = json!({"version": version, "groups": groups, "multivariate": false, "feature_enrollment": "invalid", "opaque": "x".repeat(8192)});
            let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
                "flags": [flag(filters.clone()), {"id": 2, "team_id": 1, "key": "healthy", "active": true, "filters": {"groups": [{"rollout_percentage": 100}]}}],
                "evaluation_metadata": {"dependency_stages": [[1, 2]], "flags_with_missing_deps": [], "transitive_deps": {"1": [], "2": []}}
            })).unwrap();
            assert!(!wrapper.flags[0].filters.is_v1());
            assert_eq!(
                serde_json::to_value(&wrapper).unwrap()["flags"][0]["filters"],
                filters
            );
            assert_eq!(wrapper.flags[1].filters.groups.len(), 1);
            assert!(extract_cohort_ids_from_flag_filters(&wrapper.flags).is_empty());
            let metadata = compute_flag_dependencies(&wrapper.flags).unwrap();
            assert_eq!(metadata.dependency_stages, vec![vec![1, 2]]);
            assert!(metadata.flags_with_missing_deps.is_empty());
            let prepared = PreparedFlagDefinitions {
                flags: PreparedFlags::seal(wrapper.flags),
                evaluation_metadata: Arc::new(EvaluationMetadata::default()),
                cohorts: None,
            };
            assert!(prepared.estimated_size_bytes() > 8192);
            assert!(prepared.flags[0].filters.groups.is_empty());
            assert!(prepared.flags[0].filters.require_v1().is_err());
        }
    }
}

#[test]
fn invalid_v1_filter_documents_keep_ingress_errors() {
    for filters in [
        Value::Null,
        json!(false),
        json!(1),
        json!("filters"),
        json!([]),
        json!([2]),
        json!([1]),
        json!({"groups": null}),
        json!({"groups": [{"properties": [{"key": "missing-type"}]}]}),
    ] {
        assert!(serde_json::from_value::<FeatureFlag>(flag(filters.clone())).is_err());
        assert!(decode_filters(filters).is_err());
    }
    let mut missing = flag(json!({}));
    missing.as_object_mut().unwrap().remove("filters");
    assert!(serde_json::from_value::<FeatureFlag>(missing).is_err());
    let empty: FeatureFlag = serde_json::from_value(flag(json!({}))).unwrap();
    assert!(empty.filters.groups.is_empty());
}

#[test]
fn v2_ingress_counts_parse_outcomes_without_configuration_labels() {
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    let recorder = DebuggingRecorder::new();
    let valid =
        json!({"version": 2, "return_type": "boolean", "default_value": false, "rules": []});
    let mut malformed = valid.clone();
    malformed["default_value"] = json!("invalid");
    let mut unsupported = valid.clone();
    unsupported["return_type"] = json!("string");
    let mut oversized = valid.clone();
    oversized["extra"] = json!("x".repeat(*config_v2::MAX_CONFIG_BYTES));
    metrics::with_local_recorder(&recorder, || {
        for document in [
            valid,
            malformed,
            unsupported,
            oversized,
            json!({}),
            json!({"version": 3}),
        ] {
            decode_filters(document).unwrap();
        }
    });
    let outcomes: std::collections::BTreeSet<_> = recorder
        .snapshotter()
        .snapshot()
        .into_vec()
        .into_iter()
        .filter(|(key, _, _, _)| key.key().name() == FLAG_V2_PARSE_COUNTER)
        .map(|(key, _, _, value)| {
            assert_eq!(value, DebugValue::Counter(1));
            let labels: Vec<_> = key.key().labels().collect();
            assert_eq!(labels.len(), 1);
            assert_eq!(labels[0].key(), "outcome");
            labels[0].value().to_owned()
        })
        .collect();
    assert_eq!(
        outcomes,
        ["success", "malformed", "unsupported", "limit_exceeded"]
            .into_iter()
            .map(str::to_owned)
            .collect()
    );
}
