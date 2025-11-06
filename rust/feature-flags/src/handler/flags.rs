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
use common_types::ProjectId;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use uuid::Uuid;

use super::{evaluation, types::FeatureFlagEvaluationContext};
use crate::router;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum EvaluationRuntime {
    All,
    Client,
    Server,
}

impl<'de> Deserialize<'de> for EvaluationRuntime {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        match s.to_lowercase().as_str() {
            "all" => Ok(EvaluationRuntime::All),
            "client" => Ok(EvaluationRuntime::Client),
            "server" => Ok(EvaluationRuntime::Server),
            invalid => {
                tracing::warn!(
                    "Invalid evaluation_runtime value '{}', defaulting to 'all'",
                    invalid
                );
                Ok(EvaluationRuntime::All)
            }
        }
    }
}

impl From<String> for EvaluationRuntime {
    fn from(s: String) -> Self {
        EvaluationRuntime::from(s.as_str())
    }
}

impl From<&str> for EvaluationRuntime {
    fn from(s: &str) -> Self {
        if s.eq_ignore_ascii_case("client") {
            EvaluationRuntime::Client
        } else if s.eq_ignore_ascii_case("server") {
            EvaluationRuntime::Server
        } else {
            EvaluationRuntime::All
        }
    }
}

/// Determines the evaluation runtime based on request characteristics.
/// Uses explicit runtime if provided; otherwise analyzes user-agent and headers
/// to detect if the request is from a client-side (browser/mobile) or server-side SDK.
fn detect_evaluation_runtime_from_request(
    headers: &axum::http::HeaderMap,
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
            || user_agent.starts_with("posthog-dotnet/")
            || user_agent.starts_with("posthog-elixir/")
            || user_agent.contains("python-requests/")
            || user_agent.contains("curl/")
        {
            return Some(EvaluationRuntime::Server);
        }

        // Mobile SDK patterns - these indicate client-side mobile execution
        if user_agent.starts_with("posthog-android/")
            || user_agent.starts_with("posthog-ios/")
            || user_agent.starts_with("posthog-react-native/")
            || user_agent.starts_with("posthog-flutter/")
        {
            return Some(EvaluationRuntime::Client);
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
///
/// Note: When specific flags are requested via flag_keys, they will be evaluated
/// after this runtime filtering step. The runtime filter helps prevent unnecessary
/// evaluation of flags that don't match the current runtime environment.
fn filter_flags_by_runtime(
    flags: Vec<FeatureFlag>,
    current_runtime: Option<EvaluationRuntime>,
) -> Vec<FeatureFlag> {
    #[inline]
    fn flag_runtime(flag: &FeatureFlag) -> Option<EvaluationRuntime> {
        flag.evaluation_runtime
            .as_deref()
            .map(EvaluationRuntime::from)
    }

    match current_runtime {
        Some(EvaluationRuntime::All) => {
            // All runtime can evaluate any flag
            flags
        }
        runtime_opt => flags
            .into_iter()
            .filter(|flag| match flag_runtime(flag) {
                // Include flags that:
                // 1. Have no specific runtime requirement (backward compatibility)
                // 2. Are configured for "all" runtimes
                None | Some(EvaluationRuntime::All) => true,
                // 3. Are specifically configured for the current runtime
                Some(flag_rt) => match runtime_opt {
                    Some(current_rt) => flag_rt == current_rt,
                    None => false,
                },
            })
            .collect(),
    }
}

pub async fn fetch_and_filter(
    flag_service: &FlagService,
    project_id: ProjectId,
    query_params: &FlagsQueryParams,
    headers: &axum::http::HeaderMap,
    explicit_runtime: Option<EvaluationRuntime>,
    environment_tags: Option<&Vec<String>>,
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
    let current_runtime = detect_evaluation_runtime_from_request(headers, explicit_runtime);
    let flags_after_runtime_filter =
        filter_flags_by_runtime(flags_after_survey_filter, current_runtime);

    // Finally filter by evaluation tags
    let flags_after_tag_filter =
        filter_flags_by_evaluation_tags(flags_after_runtime_filter, environment_tags);

    tracing::debug!(
        "Flag filtering: detected_runtime={:?}, environment_tags={:?}, final_count={}",
        current_runtime,
        environment_tags,
        flags_after_tag_filter.len()
    );

    Ok((FeatureFlagList::new(flags_after_tag_filter), false))
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

/// Filters flags based on evaluation tags.
/// Only includes flags that either:
/// 1. Have no evaluation tags (backward compatibility)
/// 2. Have at least one evaluation tag that matches the provided environment tags
fn filter_flags_by_evaluation_tags(
    flags: Vec<FeatureFlag>,
    environment_tags: Option<&Vec<String>>,
) -> Vec<FeatureFlag> {
    let env_tags = match environment_tags {
        Some(t) if !t.is_empty() => t,
        _ => return flags,
    };

    flags
        .into_iter()
        .filter(|flag| match &flag.evaluation_tags {
            None => true,
            Some(flag_tags) if flag_tags.is_empty() => true,
            Some(flag_tags) => flag_tags.iter().any(|tag| env_tags.contains(tag)),
        })
        .collect()
}

#[allow(clippy::too_many_arguments)]
pub async fn evaluate_for_request(
    state: &State<router::State>,
    team_id: i32,
    project_id: ProjectId,
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
        persons_reader: state.database_pools.persons_reader.clone(),
        persons_writer: state.database_pools.persons_writer.clone(),
        non_persons_reader: state.database_pools.non_persons_reader.clone(),
        non_persons_writer: state.database_pools.non_persons_writer.clone(),
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
            name: Some(format!("Test Flag {id}")),
            key: key.to_string(),
            filters: FlagFilters::default(),
            deleted: false,
            active: true,
            ensure_experience_continuity: None,
            version: None,
            evaluation_runtime,
            evaluation_tags: None,
        }
    }

    fn create_test_flag_with_tags(
        id: i32,
        key: &str,
        evaluation_runtime: Option<String>,
        evaluation_tags: Option<Vec<String>>,
    ) -> FeatureFlag {
        FeatureFlag {
            id,
            team_id: 1,
            name: Some(format!("Test Flag {id}")),
            key: key.to_string(),
            filters: FlagFilters::default(),
            deleted: false,
            active: true,
            ensure_experience_continuity: None,
            version: None,
            evaluation_runtime,
            evaluation_tags,
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

        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));
    }

    #[test]
    fn test_detect_evaluation_runtime_server_user_agent() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "posthog-python/1.2.3".parse().unwrap());

        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Server));
    }

    #[test]
    fn test_detect_evaluation_runtime_browser_headers() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("origin", "https://example.com".parse().unwrap());
        headers.insert("sec-fetch-mode", "cors".parse().unwrap());

        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));
    }

    // Removed lib_version-based detection tests as lib_version is no longer used

    #[test]
    fn test_detect_evaluation_runtime_explicit_override() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "Mozilla/5.0 (Browser)".parse().unwrap());

        // Explicit runtime should override detection
        let result =
            detect_evaluation_runtime_from_request(&headers, Some(EvaluationRuntime::Server));
        assert_eq!(result, Some(EvaluationRuntime::Server));
    }

    #[test]
    fn test_detect_evaluation_runtime_unknown() {
        let headers = axum::http::HeaderMap::new();

        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, None);
    }

    #[test]
    fn test_detect_evaluation_runtime_dotnet_sdk() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "posthog-dotnet/2.0.0".parse().unwrap());

        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Server));
    }

    #[test]
    fn test_detect_evaluation_runtime_elixir_sdk() {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "posthog-elixir/0.1.0".parse().unwrap());

        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Server));
    }

    #[test]
    fn test_detect_evaluation_runtime_mobile_sdks() {
        // iOS SDK
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "posthog-ios/3.0.0".parse().unwrap());
        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));

        // React Native SDK
        headers.clear();
        headers.insert("user-agent", "posthog-react-native/2.5.0".parse().unwrap());
        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));

        // Flutter SDK
        headers.clear();
        headers.insert("user-agent", "posthog-flutter/4.0.0".parse().unwrap());
        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));
    }

    #[test]
    fn test_detect_evaluation_runtime_android_sdk() {
        // Android SDK uses "posthog-android/" as its user agent
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("user-agent", "posthog-android/3.1.0".parse().unwrap());

        let result = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(result, Some(EvaluationRuntime::Client));
    }

    #[test]
    fn test_detect_evaluation_runtime_all_server_sdks() {
        let server_sdks = vec![
            "posthog-python/1.4.0",
            "posthog-ruby/2.0.0",
            "posthog-php/3.0.0",
            "posthog-java/1.0.0",
            "posthog-go/0.1.0",
            "posthog-node/2.2.0",
            "posthog-dotnet/1.0.0",
            "posthog-elixir/0.2.0",
        ];

        for sdk in server_sdks {
            let mut headers = axum::http::HeaderMap::new();
            headers.insert("user-agent", sdk.parse().unwrap());
            let result = detect_evaluation_runtime_from_request(&headers, None);
            assert_eq!(
                result,
                Some(EvaluationRuntime::Server),
                "SDK {sdk} should be detected as server-side"
            );
        }
    }

    #[test]
    fn test_detect_evaluation_runtime_all_browser_patterns() {
        let browser_patterns = vec![
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/91.0.4472.124",
            "Mozilla/5.0 (X11; Linux x86_64) Firefox/89.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/91.0.864.59",
        ];

        for pattern in browser_patterns {
            let mut headers = axum::http::HeaderMap::new();
            headers.insert("user-agent", pattern.parse().unwrap());
            let result = detect_evaluation_runtime_from_request(&headers, None);
            assert_eq!(
                result,
                Some(EvaluationRuntime::Client),
                "Browser pattern {pattern} should be detected as client-side"
            );
        }
    }

    #[test]
    fn test_filter_flags_with_explicit_flag_keys_should_respect_runtime() {
        // Test scenario from @haacked's comment:
        // When specific flags are requested via flag_keys (flags_to_evaluate),
        // they still need to respect runtime filtering for security/correctness.
        // Only flags that match the runtime should be evaluated.

        let flags = vec![
            create_test_flag(1, "client-flag", Some("client".to_string())),
            create_test_flag(2, "server-flag", Some("server".to_string())),
            create_test_flag(3, "all-flag", Some("all".to_string())),
        ];

        // Client runtime should only get client and all flags
        let filtered = filter_flags_by_runtime(flags, Some(EvaluationRuntime::Client));
        assert_eq!(filtered.len(), 2);
        assert!(filtered.iter().any(|f| f.key == "client-flag"));
        assert!(filtered.iter().any(|f| f.key == "all-flag"));
        assert!(!filtered.iter().any(|f| f.key == "server-flag"));

        // Note: The actual flag_keys filtering happens later in the evaluation pipeline
        // after runtime filtering, so explicitly requested flags still go through runtime checks
    }

    #[test]
    fn test_runtime_filtering_takes_precedence_over_flag_keys() {
        // This test verifies that runtime filtering happens BEFORE flag_keys filtering
        // So if a client explicitly requests a server-only flag, they won't get it

        // Create flags with different runtime requirements
        let all_flags = vec![
            create_test_flag(1, "client-only-flag", Some("client".to_string())),
            create_test_flag(2, "server-only-flag", Some("server".to_string())),
            create_test_flag(3, "all-flag", Some("all".to_string())),
            create_test_flag(4, "no-runtime-flag", None),
        ];

        // Simulate a client runtime
        let client_runtime = Some(EvaluationRuntime::Client);
        let client_filtered = filter_flags_by_runtime(all_flags.clone(), client_runtime);

        // Client should get: client-only-flag, all-flag, no-runtime-flag
        // But NOT server-only-flag
        assert_eq!(client_filtered.len(), 3);
        assert!(client_filtered.iter().any(|f| f.key == "client-only-flag"));
        assert!(client_filtered.iter().any(|f| f.key == "all-flag"));
        assert!(client_filtered.iter().any(|f| f.key == "no-runtime-flag"));
        assert!(!client_filtered.iter().any(|f| f.key == "server-only-flag"));

        // Simulate a server runtime
        let server_runtime = Some(EvaluationRuntime::Server);
        let filtered = filter_flags_by_runtime(all_flags, server_runtime);

        // Server should get: server-only-flag, all-flag, no-runtime-flag
        // But NOT client-only-flag
        assert_eq!(filtered.len(), 3);
        assert!(filtered.iter().any(|f| f.key == "server-only-flag"));
        assert!(filtered.iter().any(|f| f.key == "all-flag"));
        assert!(filtered.iter().any(|f| f.key == "no-runtime-flag"));
        assert!(!filtered.iter().any(|f| f.key == "client-only-flag"));

        // Note: Even if flag_keys explicitly requests a server-only flag from a client,
        // the runtime filter will prevent it from being evaluated
    }

    #[test]
    fn test_filter_flags_by_evaluation_tags_no_environment_tags() {
        // When no environment tags are provided, all flags should be returned
        let flags = vec![
            create_test_flag_with_tags(1, "flag1", None, None),
            create_test_flag_with_tags(2, "flag2", None, Some(vec!["app".to_string()])),
            create_test_flag_with_tags(
                3,
                "flag3",
                None,
                Some(vec!["docs".to_string(), "marketing".to_string()]),
            ),
        ];

        let filtered = filter_flags_by_evaluation_tags(flags.clone(), None);
        assert_eq!(filtered.len(), 3);

        let filtered = filter_flags_by_evaluation_tags(flags.clone(), Some(&vec![]));
        assert_eq!(filtered.len(), 3);
    }

    #[test]
    fn test_filter_flags_by_evaluation_tags_with_matching_tags() {
        let flags = vec![
            create_test_flag_with_tags(1, "no-tags", None, None),
            create_test_flag_with_tags(2, "app-only", None, Some(vec!["app".to_string()])),
            create_test_flag_with_tags(3, "docs-only", None, Some(vec!["docs".to_string()])),
            create_test_flag_with_tags(
                4,
                "multi-env",
                None,
                Some(vec!["app".to_string(), "docs".to_string()]),
            ),
        ];

        // Test with "app" environment
        let app_env = vec!["app".to_string()];
        let filtered = filter_flags_by_evaluation_tags(flags.clone(), Some(&app_env));
        assert_eq!(filtered.len(), 3); // no-tags, app-only, multi-env
        assert!(filtered.iter().any(|f| f.key == "no-tags"));
        assert!(filtered.iter().any(|f| f.key == "app-only"));
        assert!(filtered.iter().any(|f| f.key == "multi-env"));
        assert!(!filtered.iter().any(|f| f.key == "docs-only"));

        // Test with "docs" environment
        let docs_env = vec!["docs".to_string()];
        let filtered = filter_flags_by_evaluation_tags(flags.clone(), Some(&docs_env));
        assert_eq!(filtered.len(), 3); // no-tags, docs-only, multi-env
        assert!(filtered.iter().any(|f| f.key == "no-tags"));
        assert!(filtered.iter().any(|f| f.key == "docs-only"));
        assert!(filtered.iter().any(|f| f.key == "multi-env"));
        assert!(!filtered.iter().any(|f| f.key == "app-only"));
    }

    #[test]
    fn test_filter_flags_by_evaluation_tags_no_matching_tags() {
        let flags = vec![
            create_test_flag_with_tags(1, "app-only", None, Some(vec!["app".to_string()])),
            create_test_flag_with_tags(2, "docs-only", None, Some(vec!["docs".to_string()])),
        ];

        // Test with unmatched environment
        let marketing_env = vec!["marketing".to_string()];
        let filtered = filter_flags_by_evaluation_tags(flags.clone(), Some(&marketing_env));
        assert_eq!(filtered.len(), 0);
    }

    #[test]
    fn test_filter_flags_by_evaluation_tags_empty_flag_tags() {
        // Flags with empty evaluation_tags should be included (backward compatibility)
        let flags = vec![
            create_test_flag_with_tags(1, "empty-tags", None, Some(vec![])),
            create_test_flag_with_tags(2, "app-only", None, Some(vec!["app".to_string()])),
        ];

        let app_env = vec!["app".to_string()];
        let filtered = filter_flags_by_evaluation_tags(flags.clone(), Some(&app_env));
        assert_eq!(filtered.len(), 2);
        assert!(filtered.iter().any(|f| f.key == "empty-tags"));
        assert!(filtered.iter().any(|f| f.key == "app-only"));
    }

    #[test]
    fn test_filter_flags_by_evaluation_tags_multiple_environment_tags() {
        let flags = vec![
            create_test_flag_with_tags(1, "app-only", None, Some(vec!["app".to_string()])),
            create_test_flag_with_tags(2, "docs-only", None, Some(vec!["docs".to_string()])),
            create_test_flag_with_tags(
                3,
                "marketing-only",
                None,
                Some(vec!["marketing".to_string()]),
            ),
            create_test_flag_with_tags(4, "no-tags", None, None),
        ];

        // Test with multiple environment tags - should match ANY of them
        let multi_env = vec!["app".to_string(), "docs".to_string()];
        let filtered = filter_flags_by_evaluation_tags(flags.clone(), Some(&multi_env));
        assert_eq!(filtered.len(), 3); // app-only, docs-only, no-tags
        assert!(filtered.iter().any(|f| f.key == "app-only"));
        assert!(filtered.iter().any(|f| f.key == "docs-only"));
        assert!(filtered.iter().any(|f| f.key == "no-tags"));
        assert!(!filtered.iter().any(|f| f.key == "marketing-only"));
    }

    #[test]
    fn test_explicit_runtime_overrides_detection() {
        // This test verifies that when an explicit runtime is provided,
        // it takes precedence over any auto-detection based on headers

        let mut headers = axum::http::HeaderMap::new();
        // Add a browser user-agent that would normally be detected as "client"
        headers.insert(
            "user-agent",
            "Mozilla/5.0 Chrome/120.0.0.0".parse().unwrap(),
        );
        headers.insert("origin", "https://app.posthog.com".parse().unwrap());

        // Test 1: Explicit "server" should override client detection
        let runtime =
            detect_evaluation_runtime_from_request(&headers, Some(EvaluationRuntime::Server));
        assert_eq!(
            runtime,
            Some(EvaluationRuntime::Server),
            "Explicit server runtime should override client headers"
        );

        // Test 2: Explicit "client" with server-like headers
        headers.clear();
        headers.insert("user-agent", "posthog-python/3.0.0".parse().unwrap());
        let runtime =
            detect_evaluation_runtime_from_request(&headers, Some(EvaluationRuntime::Client));
        assert_eq!(
            runtime,
            Some(EvaluationRuntime::Client),
            "Explicit client runtime should override server headers"
        );

        // Test 3: Explicit "all" overrides any detection
        let runtime =
            detect_evaluation_runtime_from_request(&headers, Some(EvaluationRuntime::All));
        assert_eq!(
            runtime,
            Some(EvaluationRuntime::All),
            "Explicit all runtime should be preserved"
        );

        // Test 4: No explicit runtime falls back to auto-detection
        let runtime = detect_evaluation_runtime_from_request(&headers, None);
        assert_eq!(
            runtime,
            Some(EvaluationRuntime::Server),
            "Without explicit runtime, should detect server from python user-agent"
        );
    }
}
