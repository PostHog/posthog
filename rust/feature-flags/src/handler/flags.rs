use crate::{
    api::{
        errors::FlagError,
        types::{FlagsQueryParams, FlagsResponse},
    },
    flags::{
        flag_analytics::SURVEY_TARGETING_FLAG_PREFIX,
        flag_models::{FeatureFlag, FeatureFlagList},
        flag_service::FlagService,
    },
};
use axum::extract::State;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use uuid::Uuid;

use super::{evaluation, types::FeatureFlagEvaluationContext};
use crate::router;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum EvaluationRuntime {
    All,
    Client,
    Server,
}

impl From<String> for EvaluationRuntime {
    fn from(s: String) -> Self {
        match s.to_lowercase().as_str() {
            "client" => EvaluationRuntime::Client,
            "server" => EvaluationRuntime::Server,
            "all" | _ => EvaluationRuntime::All,
        }
    }
}

impl From<&str> for EvaluationRuntime {
    fn from(s: &str) -> Self {
        EvaluationRuntime::from(s.to_string())
    }
}

// TODO: Implement logic to determine current evaluation runtime
// For now, this is a placeholder that will need to be replaced with actual runtime detection
fn get_current_evaluation_runtime(
    explicit_runtime: Option<EvaluationRuntime>,
) -> Option<EvaluationRuntime> {
    // Use explicitly passed runtime if available
    if let Some(runtime) = explicit_runtime {
        return Some(runtime);
    }

    // Placeholder for automatic runtime detection - this could come from:
    // - Request headers
    // - Environment variables
    // - Team/project configuration
    // - Client SDK version/type
    None
}

/// Filters flags to only include those that can be evaluated in the current runtime.
/// If no runtime is specified for a flag (evaluation_runtime is None), it's included
/// to maintain backward compatibility.
fn filter_flags_by_runtime(
    flags: Vec<FeatureFlag>,
    current_runtime: Option<EvaluationRuntime>,
) -> Vec<FeatureFlag> {
    match current_runtime {
        Some(EvaluationRuntime::All) => {
            // All runtime can evaluate any flag
            flags
        }
        Some(runtime) => flags
            .into_iter()
            .filter(|flag| {
                // Include flags that:
                // 1. Have no specific runtime requirement (backward compatibility)
                // 2. Are configured for "all" runtimes
                // 3. Are specifically configured for the current runtime
                flag.evaluation_runtime.is_none()
                    || flag
                        .evaluation_runtime
                        .as_ref()
                        .map(|r| EvaluationRuntime::from(r.as_str()))
                        == Some(EvaluationRuntime::All)
                    || flag
                        .evaluation_runtime
                        .as_ref()
                        .map(|r| EvaluationRuntime::from(r.as_str()))
                        == Some(runtime)
            })
            .collect(),
        None => {
            // If we can't determine the current runtime, only return flags
            // that don't specify a runtime requirement or are set to "all"
            flags
                .into_iter()
                .filter(|flag| {
                    flag.evaluation_runtime.is_none()
                        || flag
                            .evaluation_runtime
                            .as_ref()
                            .map(|r| EvaluationRuntime::from(r.as_str()))
                            == Some(EvaluationRuntime::All)
                })
                .collect()
        }
    }
}

pub async fn fetch_and_filter(
    flag_service: &FlagService,
    project_id: i64,
    query_params: &FlagsQueryParams,
    evaluation_runtime: Option<EvaluationRuntime>,
) -> Result<(FeatureFlagList, bool), FlagError> {
    let flag_result = flag_service.get_flags_from_cache_or_pg(project_id).await?;

    // First filter by survey flags if requested
    let flags_after_survey_filter = filter_survey_flags(
        flag_result.flag_list.flags,
        query_params
            .only_evaluate_survey_feature_flags
            .unwrap_or(false),
    );

    // Then filter by evaluation runtime
    let current_runtime = get_current_evaluation_runtime(evaluation_runtime);
    let flags_after_runtime_filter =
        filter_flags_by_runtime(flags_after_survey_filter, current_runtime.clone());

    tracing::debug!(
        "Runtime filtering: current_runtime={:?}, flags_count={}",
        current_runtime,
        flags_after_runtime_filter.len()
    );

    Ok((
        FeatureFlagList::new(flags_after_runtime_filter),
        flag_result.had_deserialization_errors,
    ))
}

/// Filters flags to only include survey flags if requested
/// This field is optional, passed in as a query param, and defaults to false
fn filter_survey_flags(flags: Vec<FeatureFlag>, only_survey_flags: bool) -> Vec<FeatureFlag> {
    if only_survey_flags {
        flags
            .into_iter()
            .filter(|flag| flag.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
            .collect()
    } else {
        flags
    }
}

#[allow(clippy::too_many_arguments)]
pub async fn evaluate_for_request(
    state: &State<router::State>,
    team_id: i32,
    project_id: i64,
    distinct_id: String,
    filtered_flags: FeatureFlagList,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    groups: Option<HashMap<String, Value>>,
    hash_key_override: Option<String>,
    request_id: Uuid,
    disable_flags: bool,
    flag_keys: Option<Vec<String>>,
) -> FlagsResponse {
    // If flags are disabled, return empty FlagsResponse
    if disable_flags {
        return FlagsResponse::new(false, HashMap::new(), None, request_id);
    }

    if filtered_flags.flags.is_empty() {
        return FlagsResponse::new(false, HashMap::new(), None, request_id);
    }

    let ctx = FeatureFlagEvaluationContext {
        team_id,
        project_id,
        distinct_id,
        feature_flags: filtered_flags,
        reader: state.reader.clone(),
        writer: state.writer.clone(),
        cohort_cache: state.cohort_cache_manager.clone(),
        person_property_overrides,
        group_property_overrides,
        groups,
        hash_key_override,
        flag_keys,
    };

    evaluation::evaluate_feature_flags(ctx, request_id).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{FeatureFlag, FlagFilters};

    fn create_test_flag(id: i32, key: &str, evaluation_runtime: Option<String>) -> FeatureFlag {
        FeatureFlag {
            id,
            team_id: 1,
            name: Some(format!("Test Flag {}", id)),
            key: key.to_string(),
            filters: FlagFilters::default(),
            deleted: false,
            active: true,
            ensure_experience_continuity: None,
            version: None,
            evaluation_runtime,
        }
    }

    #[test]
    fn test_filter_flags_by_runtime_with_no_runtime() {
        let flags = vec![
            create_test_flag(1, "flag1", None),
            create_test_flag(2, "flag2", Some("client".to_string())),
            create_test_flag(3, "flag3", Some("server".to_string())),
            create_test_flag(4, "flag4", Some("all".to_string())),
        ];

        let filtered = filter_flags_by_runtime(flags, None);

        // Should only return flags with no runtime requirement or "all"
        assert_eq!(filtered.len(), 2);
        assert!(filtered.iter().any(|f| f.key == "flag1"));
        assert!(filtered.iter().any(|f| f.key == "flag4"));
    }

    #[test]
    fn test_filter_flags_by_runtime_with_client() {
        let flags = vec![
            create_test_flag(1, "flag1", None),
            create_test_flag(2, "flag2", Some("client".to_string())),
            create_test_flag(3, "flag3", Some("server".to_string())),
            create_test_flag(4, "flag4", Some("all".to_string())),
        ];

        let filtered = filter_flags_by_runtime(flags, Some(EvaluationRuntime::Client));

        // Should return flags with no runtime requirement + client flags + all flags
        assert_eq!(filtered.len(), 3);
        assert!(filtered.iter().any(|f| f.key == "flag1"));
        assert!(filtered.iter().any(|f| f.key == "flag2"));
        assert!(filtered.iter().any(|f| f.key == "flag4"));
        assert!(!filtered.iter().any(|f| f.key == "flag3"));
    }

    #[test]
    fn test_filter_flags_by_runtime_with_server() {
        let flags = vec![
            create_test_flag(1, "flag1", None),
            create_test_flag(2, "flag2", Some("client".to_string())),
            create_test_flag(3, "flag3", Some("server".to_string())),
            create_test_flag(4, "flag4", Some("all".to_string())),
        ];

        let filtered = filter_flags_by_runtime(flags, Some(EvaluationRuntime::Server));

        // Should return flags with no runtime requirement + server flags + all flags
        assert_eq!(filtered.len(), 3);
        assert!(filtered.iter().any(|f| f.key == "flag1"));
        assert!(filtered.iter().any(|f| f.key == "flag3"));
        assert!(filtered.iter().any(|f| f.key == "flag4"));
        assert!(!filtered.iter().any(|f| f.key == "flag2"));
    }

    #[test]
    fn test_filter_flags_by_runtime_with_all() {
        let flags = vec![
            create_test_flag(1, "flag1", None),
            create_test_flag(2, "flag2", Some("client".to_string())),
            create_test_flag(3, "flag3", Some("server".to_string())),
            create_test_flag(4, "flag4", Some("all".to_string())),
        ];

        let filtered = filter_flags_by_runtime(flags, Some(EvaluationRuntime::All));

        // Should return all flags since All runtime should include everything
        assert_eq!(filtered.len(), 4);
        assert!(filtered.iter().any(|f| f.key == "flag1"));
        assert!(filtered.iter().any(|f| f.key == "flag2"));
        assert!(filtered.iter().any(|f| f.key == "flag3"));
        assert!(filtered.iter().any(|f| f.key == "flag4"));
    }

    #[test]
    fn test_filter_flags_by_runtime_with_unknown_value() {
        let flags = vec![
            create_test_flag(1, "flag1", None),
            create_test_flag(2, "flag2", Some("client".to_string())),
            create_test_flag(3, "flag3", Some("unknown_runtime".to_string())),
            create_test_flag(4, "flag4", Some("all".to_string())),
        ];

        let filtered = filter_flags_by_runtime(flags, Some(EvaluationRuntime::Client));

        // Unknown runtime values default to "all", so "unknown_runtime" flag should be included
        assert_eq!(filtered.len(), 4);
        assert!(filtered.iter().any(|f| f.key == "flag1"));
        assert!(filtered.iter().any(|f| f.key == "flag2"));
        assert!(filtered.iter().any(|f| f.key == "flag3")); // unknown_runtime -> all
        assert!(filtered.iter().any(|f| f.key == "flag4"));
    }

    #[test]
    fn test_evaluation_runtime_enum_from_string() {
        assert_eq!(EvaluationRuntime::from("client"), EvaluationRuntime::Client);
        assert_eq!(EvaluationRuntime::from("server"), EvaluationRuntime::Server);
        assert_eq!(EvaluationRuntime::from("all"), EvaluationRuntime::All);
        assert_eq!(EvaluationRuntime::from("CLIENT"), EvaluationRuntime::Client);
        assert_eq!(EvaluationRuntime::from("unknown"), EvaluationRuntime::All);
        assert_eq!(EvaluationRuntime::from(""), EvaluationRuntime::All);
    }

    #[test]
    fn test_get_current_evaluation_runtime_with_explicit() {
        let result = get_current_evaluation_runtime(Some(EvaluationRuntime::Client));
        assert_eq!(result, Some(EvaluationRuntime::Client));
    }

    #[test]
    fn test_get_current_evaluation_runtime_without_explicit() {
        let result = get_current_evaluation_runtime(None);
        // Should return None since we don't have automatic detection yet
        assert_eq!(result, None);
    }
}
