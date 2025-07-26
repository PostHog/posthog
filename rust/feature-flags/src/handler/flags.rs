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

/// Determines the evaluation runtime based on request characteristics.
/// Uses explicit runtime if provided, otherwise analyzes user-agent, headers, and lib_version
/// to detect if the request is from a client-side (browser/mobile) or server-side SDK.
fn detect_evaluation_runtime_from_request(
    headers: &axum::http::HeaderMap,
    lib_version: Option<&str>,
    explicit_runtime: Option<EvaluationRuntime>,
) -> Option<EvaluationRuntime> {
    // Use explicitly passed runtime if available
    if let Some(runtime) = explicit_runtime {
        return Some(runtime);
    }

    // Analyze User-Agent header
    if let Some(user_agent) = headers.get("user-agent").and_then(|v| v.to_str().ok()) {
        // Browser patterns - these typically indicate client-side execution
        if user_agent.contains("Mozilla/")
            || user_agent.contains("Chrome/")
            || user_agent.contains("Safari/")
            || user_agent.contains("Firefox/")
            || user_agent.contains("Edge/")
        {
            return Some(EvaluationRuntime::Client);
        }

        // Server SDK patterns - these indicate server-side execution
        if user_agent.starts_with("posthog-python/")
            || user_agent.starts_with("posthog-ruby/")
            || user_agent.starts_with("posthog-php/")
            || user_agent.starts_with("posthog-java/")
            || user_agent.starts_with("posthog-go/")
            || user_agent.starts_with("posthog-node/") // Note: server-side Node.js
            || user_agent.contains("python-requests/")
            || user_agent.contains("curl/")
        {
            return Some(EvaluationRuntime::Server);
        }
    }

    // Analyze lib_version for additional clues
    if let Some(lib_version) = lib_version {
        // JavaScript SDK versions often indicate client-side
        if lib_version.contains("posthog-js") || lib_version.contains("javascript") {
            return Some(EvaluationRuntime::Client);
        }

        // Server SDK patterns in lib_version
        if lib_version.contains("python")
            || lib_version.contains("ruby")
            || lib_version.contains("php")
            || lib_version.contains("java")
            || lib_version.contains("golang")
            || lib_version.contains("server")
        {
            return Some(EvaluationRuntime::Server);
        }
    }

    // Check for browser-specific headers that indicate client-side
    if headers.contains_key("origin")
        || headers.contains_key("referer")
        || headers.get("sec-fetch-mode").is_some()
        || headers.get("sec-fetch-site").is_some()
    {
        return Some(EvaluationRuntime::Client);
    }

    // If we can't determine, default to None (which will include flags with no runtime requirement + "all")
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
    headers: &axum::http::HeaderMap,
    explicit_runtime: Option<EvaluationRuntime>,
) -> Result<(FeatureFlagList, bool), FlagError> {
    let flag_result = flag_service.get_flags_from_cache_or_pg(project_id).await?;

    // First filter by survey flags if requested
    let flags_after_survey_filter = filter_survey_flags(
        flag_result.flag_list.flags,
        query_params
            .only_evaluate_survey_feature_flags
            .unwrap_or(false),
    );

    // Then filter by evaluation runtime using request analysis
    let current_runtime = detect_evaluation_runtime_from_request(
        headers,
        query_params.lib_version.as_deref(),
        explicit_runtime,
    );
    let flags_after_runtime_filter =
        filter_flags_by_runtime(flags_after_survey_filter, current_runtime);

    tracing::debug!(
        "Runtime filtering: detected_runtime={:?}, flags_count={}",
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
    fn test_detect_evaluation_runtime_browser_user_agent() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert(
            "user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                .parse()
                .unwrap(),
        );

        let result = detect_evaluation_runtime_from_request(&headers, None, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));
    }

    #[test]
    fn test_detect_evaluation_runtime_server_user_agent() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "posthog-python/1.2.3".parse().unwrap());

        let result = detect_evaluation_runtime_from_request(&headers, None, None);
        assert_eq!(result, Some(EvaluationRuntime::Server));
    }

    #[test]
    fn test_detect_evaluation_runtime_browser_headers() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("origin", "https://example.com".parse().unwrap());
        headers.insert("sec-fetch-mode", "cors".parse().unwrap());

        let result = detect_evaluation_runtime_from_request(&headers, None, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));
    }

    #[test]
    fn test_detect_evaluation_runtime_lib_version() {
        let headers = axum::http::HeaderMap::new();

        let result =
            detect_evaluation_runtime_from_request(&headers, Some("posthog-js/1.2.3"), None);
        assert_eq!(result, Some(EvaluationRuntime::Client));

        let result = detect_evaluation_runtime_from_request(&headers, Some("python/3.9"), None);
        assert_eq!(result, Some(EvaluationRuntime::Server));
    }

    #[test]
    fn test_detect_evaluation_runtime_explicit_override() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "Mozilla/5.0 (Browser)".parse().unwrap());

        // Explicit runtime should override detection
        let result =
            detect_evaluation_runtime_from_request(&headers, None, Some(EvaluationRuntime::Server));
        assert_eq!(result, Some(EvaluationRuntime::Server));
    }

    #[test]
    fn test_detect_evaluation_runtime_unknown() {
        let headers = axum::http::HeaderMap::new();

        let result = detect_evaluation_runtime_from_request(&headers, Some("unknown-sdk"), None);
        assert_eq!(result, None);
    }
}
