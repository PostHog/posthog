use crate::{
    api::{
        errors::FlagError,
        types::{FlagsQueryParams, FlagsResponse},
    },
    flags::{
        feature_flag_list::PreparedFlags,
        flag_analytics::SURVEY_TARGETING_FLAG_PREFIX,
        flag_models::{FeatureFlag, FeatureFlagList},
        flag_service::FlagService,
    },
    utils::user_agent::{RuntimeType, UserAgentInfo},
};
use axum::extract::State;
use common_types::TeamId;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use uuid::Uuid;

use super::{evaluation, types::FeatureFlagEvaluationContext, with_canonical_log};
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

    // Analyze User-Agent header using shared parsing logic
    let user_agent = headers.get("user-agent").and_then(|v| v.to_str().ok());
    let ua_info = UserAgentInfo::parse(user_agent);

    match ua_info.runtime {
        RuntimeType::Client => return Some(EvaluationRuntime::Client),
        RuntimeType::Server => return Some(EvaluationRuntime::Server),
        RuntimeType::Unknown => {}
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

/// Returns the set of flag IDs that don't match the current runtime.
/// Flags with no runtime or runtime "all" are never filtered out.
fn collect_excluded_by_runtime(
    flags: &[FeatureFlag],
    current_runtime: Option<EvaluationRuntime>,
) -> HashSet<i32> {
    #[inline]
    fn flag_runtime(flag: &FeatureFlag) -> Option<EvaluationRuntime> {
        flag.evaluation_runtime
            .as_deref()
            .map(EvaluationRuntime::from)
    }

    match current_runtime {
        Some(EvaluationRuntime::All) => HashSet::new(),
        runtime_opt => flags
            .iter()
            .filter(|flag| match (runtime_opt, flag_runtime(flag)) {
                // Flags with no runtime or "all" are never filtered
                (_, None | Some(EvaluationRuntime::All)) => false,
                (Some(current_rt), Some(flag_rt)) => flag_rt != current_rt,
                (None, Some(_)) => true,
            })
            .map(|flag| flag.id)
            .collect(),
    }
}

/// Apply caller-supplied flag overrides to ``flags``, returning the keys that
/// were successfully overridden.
///
/// The override map is keyed by flag key alone, so the override payload must
/// re-state the resolved flag's ``id``, ``team_id``, and ``key``. Mismatches
/// are dropped with a warning — a caller must not be able to swap one flag's
/// identity for another (potentially cross-team) by submitting a forged
/// override payload.
fn apply_flag_overrides(
    flags: &mut [FeatureFlag],
    override_defs: &HashMap<String, Value>,
) -> Vec<String> {
    let mut overridden_keys = Vec::new();
    tracing::debug!("Processing {} override definitions", override_defs.len());
    for (flag_key, override_def) in override_defs {
        tracing::debug!("Processing override for flag: {}", flag_key);
        let Some(flag) = flags.iter_mut().find(|f| &f.key == flag_key) else {
            tracing::warn!("Flag not found for override: {}", flag_key);
            continue;
        };
        tracing::trace!(
            "Found flag to override: {}, current filters: {:?}",
            flag_key,
            flag.filters
        );
        let override_flag = match serde_json::from_value::<FeatureFlag>(override_def.clone()) {
            Ok(parsed) => parsed,
            Err(e) => {
                tracing::warn!(
                    "Failed to parse override definition for flag {}: {}",
                    flag_key,
                    e
                );
                tracing::debug!("Override definition: {:?}", override_def);
                continue;
            }
        };
        // Identity guard: a caller must not be able to use the override to
        // swap in another flag's identity. The override is keyed by flag_key
        // alone, so we reject payloads whose embedded key/id/team_id disagree
        // with the flag we resolved from the team's flag list.
        if override_flag.key != *flag_key
            || override_flag.id != flag.id
            || override_flag.team_id != flag.team_id
        {
            tracing::warn!(
                "Override identity mismatch for flag {}: skipping (override key={:?}, id={}, team_id={}; expected key={:?}, id={}, team_id={})",
                flag_key,
                override_flag.key,
                override_flag.id,
                override_flag.team_id,
                flag.key,
                flag.id,
                flag.team_id
            );
            continue;
        }
        tracing::trace!(
            "Successfully parsed override flag: {}, new filters: {:?}",
            flag_key,
            override_flag.filters
        );
        *flag = override_flag;
        overridden_keys.push(flag_key.clone());
    }
    overridden_keys
}

pub async fn fetch_and_filter(
    flag_service: &FlagService,
    team_id: TeamId,
    query_params: &FlagsQueryParams,
    headers: &axum::http::HeaderMap,
    explicit_runtime: Option<EvaluationRuntime>,
    environment_tags: Option<&Vec<String>>,
    override_flags_definitions: Option<&HashMap<String, Value>>,
) -> Result<FeatureFlagList, FlagError> {
    let flag_result = flag_service.get_flags_from_cache_or_pg(team_id).await?;

    // Record cache source in canonical log for observability
    with_canonical_log(|log| log.flags_cache_source = Some(flag_result.cache_source.as_log_str()));

    let prepared = &flag_result.prepared;

    // Apply override flag definitions if provided. Overrides require a clone
    // because `prepared.flags` is Arc-backed and shared across requests.
    let overridden_flags: Option<PreparedFlags> = match override_flags_definitions {
        Some(override_defs) => {
            let mut flags_vec: Vec<FeatureFlag> = prepared.flags.iter().cloned().collect();
            let overridden_keys = apply_flag_overrides(&mut flags_vec, override_defs);
            if !overridden_keys.is_empty() {
                with_canonical_log(|log| {
                    log.flags_overridden = Some(overridden_keys);
                });
            }
            Some(PreparedFlags::seal(flags_vec))
        }
        None => None,
    };

    let flags: &[FeatureFlag] = match &overridden_flags {
        Some(p) => p,
        None => &prepared.flags,
    };

    // Build the filtered-out set: user-disabled, deleted, survey filter, runtime/tag mismatches.
    // This is the single source of truth for "should this flag be skipped during evaluation."
    let mut filtered_out_flag_ids: HashSet<i32> = flags
        .iter()
        .filter(|f| !f.active || f.deleted)
        .map(|f| f.id)
        .collect();

    filtered_out_flag_ids.extend(collect_excluded_by_survey_filter(
        flags,
        query_params
            .only_evaluate_survey_feature_flags
            .unwrap_or(false),
    ));
    let current_runtime = detect_evaluation_runtime_from_request(headers, explicit_runtime);
    filtered_out_flag_ids.extend(collect_excluded_by_runtime(flags, current_runtime));
    filtered_out_flag_ids.extend(collect_excluded_by_tags(flags, environment_tags));

    if tracing::enabled!(tracing::Level::DEBUG) {
        let active_count = flags
            .iter()
            .filter(|f| !filtered_out_flag_ids.contains(&f.id))
            .count();
        tracing::debug!(
            "Flag filtering: detected_runtime={:?}, environment_tags={:?}, total={}, active={}",
            current_runtime,
            environment_tags,
            flags.len(),
            active_count,
        );
    }

    // Every shared field of `prepared` is Arc-backed, so this is a handful
    // of refcount bumps rather than a deep copy of the flag slice, the
    // `EvaluationMetadata` map, or the cohort vec.
    let flag_list = FeatureFlagList {
        flags: match overridden_flags {
            Some(p) => p,
            None => PreparedFlags::from_arc(Arc::clone(prepared.flags.as_arc())),
        },
        filtered_out_flag_ids,
        evaluation_metadata: Arc::clone(&prepared.evaluation_metadata),
        cohorts: prepared.cohorts.as_ref().map(Arc::clone),
    };
    Ok(flag_list)
}

/// Returns flag IDs that should be excluded when only survey flags are requested.
/// When `only_survey_flags` is true, all non-survey flags are excluded.
fn collect_excluded_by_survey_filter(
    flags: &[FeatureFlag],
    only_survey_flags: bool,
) -> HashSet<i32> {
    if only_survey_flags {
        flags
            .iter()
            .filter(|flag| !flag.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
            .map(|f| f.id)
            .collect()
    } else {
        HashSet::new()
    }
}

/// Returns the set of flag IDs that don't match the provided evaluation tags.
/// Flags with no tags or matching tags are never filtered out.
fn collect_excluded_by_tags(
    flags: &[FeatureFlag],
    environment_tags: Option<&Vec<String>>,
) -> HashSet<i32> {
    let env_tags = match environment_tags {
        Some(t) if !t.is_empty() => t,
        _ => return HashSet::new(),
    };

    let env_tag_set: HashSet<&str> = env_tags.iter().map(|s| s.as_str()).collect();

    flags
        .iter()
        .filter(|flag| match &flag.evaluation_tags {
            None => false,
            Some(flag_tags) if flag_tags.is_empty() => false,
            Some(flag_tags) => !flag_tags
                .iter()
                .any(|tag| env_tag_set.contains(tag.as_str())),
        })
        .map(|flag| flag.id)
        .collect()
}

#[allow(clippy::too_many_arguments)]
pub async fn evaluate_for_request(
    state: &State<router::State>,
    team_id: i32,
    distinct_id: String,
    device_id: Option<String>,
    filtered_flags: FeatureFlagList,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    groups: Option<HashMap<String, Value>>,
    hash_key_override: Option<String>,
    request_id: Uuid,
    disable_flags: bool,
    flag_keys: Option<Vec<String>>,
    detailed_analysis: Option<bool>,
    only_use_override_person_properties: Option<bool>,
) -> Result<FlagsResponse, FlagError> {
    // If flags are disabled, return empty FlagsResponse
    if disable_flags {
        return Ok(FlagsResponse::new(false, HashMap::new(), None, request_id));
    }

    if filtered_flags.flags.is_empty() {
        return Ok(FlagsResponse::new(false, HashMap::new(), None, request_id));
    }

    // Every flag is in the filter set (inactive, deleted, runtime/tag mismatch) — nothing to evaluate.
    // This is O(1) since the filter set includes deleted flags.
    if filtered_flags.filtered_out_flag_ids.len() >= filtered_flags.flags.len() {
        return Ok(FlagsResponse::new(false, HashMap::new(), None, request_id));
    }

    let ctx = FeatureFlagEvaluationContext {
        team_id,
        distinct_id,
        device_id,
        feature_flags: filtered_flags,
        persons_reader: state.database_pools.persons_reader.clone(),
        persons_writer: state.database_pools.persons_writer.clone(),
        non_persons_reader: state.database_pools.non_persons_reader.clone(),
        non_persons_writer: state.database_pools.non_persons_writer.clone(),
        cohort_cache: state.cohort_cache_manager.clone(),
        group_type_cache: state.group_type_cache_manager.clone(),
        person_property_overrides,
        group_property_overrides,
        groups,
        hash_key_override,
        flag_keys,
        optimize_experience_continuity_lookups: state
            .config
            .optimize_experience_continuity_lookups
            .0,
        parallel_eval_threshold: state.config.parallel_eval_threshold,
        rayon_dispatcher: state.rayon_dispatcher.clone(),
        skip_writes: detailed_analysis.unwrap_or(false)
            || only_use_override_person_properties.unwrap_or(false)
            || *state.config.skip_writes,
        cohort_membership_provider: state.cohort_membership_provider.clone(),
        enable_realtime_cohort_evaluation: state
            .config
            .realtime_cohort_evaluation_team_ids
            .includes_team(team_id),
        detailed_analysis: detailed_analysis.unwrap_or(false),
        only_use_override_person_properties: only_use_override_person_properties.unwrap_or(false),
    };

    evaluation::evaluate_feature_flags(ctx, request_id).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::FeatureFlag;
    use crate::mock;
    use crate::utils::mock::MockInto;

    fn flag(id: i32, key: &str, runtime: Option<&str>, tags: Option<Vec<String>>) -> FeatureFlag {
        mock!(FeatureFlag,
            id: id,
            key: key.mock_into(),
            evaluation_runtime: runtime.map(String::from),
            evaluation_tags: tags
        )
    }

    fn assert_filtered(filtered: &HashSet<i32>, flags: &[FeatureFlag], key: &str, expected: bool) {
        let flag = flags
            .iter()
            .find(|f| f.key == key)
            .unwrap_or_else(|| panic!("flag '{key}' not found"));
        let is_filtered = filtered.contains(&flag.id);
        assert_eq!(
            is_filtered, expected,
            "flag '{key}' (id={}) expected filtered_out={expected}, got filtered_out={is_filtered}",
            flag.id
        );
    }

    #[test]
    fn test_collect_excluded_by_runtime_with_no_runtime() {
        let flags = vec![
            flag(1, "flag1", None, None),
            flag(2, "flag2", Some("client"), None),
            flag(3, "flag3", Some("server"), None),
            flag(4, "flag4", Some("all"), None),
        ];

        let filtered = collect_excluded_by_runtime(&flags, None);

        // client/server-specific ones are filtered out
        assert_filtered(&filtered, &flags, "flag1", false);
        assert_filtered(&filtered, &flags, "flag2", true);
        assert_filtered(&filtered, &flags, "flag3", true);
        assert_filtered(&filtered, &flags, "flag4", false);
    }

    #[test]
    fn test_collect_excluded_by_runtime_with_client() {
        let flags = vec![
            flag(1, "flag1", None, None),
            flag(2, "flag2", Some("client"), None),
            flag(3, "flag3", Some("server"), None),
            flag(4, "flag4", Some("all"), None),
        ];

        let filtered = collect_excluded_by_runtime(&flags, Some(EvaluationRuntime::Client));

        // Server-only flag filtered out
        assert_filtered(&filtered, &flags, "flag1", false);
        assert_filtered(&filtered, &flags, "flag2", false);
        assert_filtered(&filtered, &flags, "flag3", true);
        assert_filtered(&filtered, &flags, "flag4", false);
    }

    #[test]
    fn test_collect_excluded_by_runtime_with_server() {
        let flags = vec![
            flag(1, "flag1", None, None),
            flag(2, "flag2", Some("client"), None),
            flag(3, "flag3", Some("server"), None),
            flag(4, "flag4", Some("all"), None),
        ];

        let filtered = collect_excluded_by_runtime(&flags, Some(EvaluationRuntime::Server));

        // Client-only flag filtered out
        assert_filtered(&filtered, &flags, "flag1", false);
        assert_filtered(&filtered, &flags, "flag2", true);
        assert_filtered(&filtered, &flags, "flag3", false);
        assert_filtered(&filtered, &flags, "flag4", false);
    }

    #[test]
    fn test_collect_excluded_by_runtime_with_all() {
        let flags = vec![
            flag(1, "flag1", None, None),
            flag(2, "flag2", Some("client"), None),
            flag(3, "flag3", Some("server"), None),
            flag(4, "flag4", Some("all"), None),
        ];

        let filtered = collect_excluded_by_runtime(&flags, Some(EvaluationRuntime::All));

        // All runtime includes everything, nothing filtered
        assert!(filtered.is_empty());
    }

    #[test]
    fn test_collect_excluded_by_runtime_with_unknown_value() {
        let flags = vec![
            flag(1, "flag1", None, None),
            flag(2, "flag2", Some("client"), None),
            flag(3, "flag3", Some("unknown_runtime"), None),
            flag(4, "flag4", Some("all"), None),
        ];

        let filtered = collect_excluded_by_runtime(&flags, Some(EvaluationRuntime::Client));

        // Unknown runtime values default to "all", so not filtered
        assert_filtered(&filtered, &flags, "flag1", false);
        assert_filtered(&filtered, &flags, "flag2", false);
        assert_filtered(&filtered, &flags, "flag3", false); // unknown_runtime -> all
        assert_filtered(&filtered, &flags, "flag4", false);
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
        let flags = vec![
            flag(1, "client-flag", Some("client"), None),
            flag(2, "server-flag", Some("server"), None),
            flag(3, "all-flag", Some("all"), None),
        ];

        let filtered = collect_excluded_by_runtime(&flags, Some(EvaluationRuntime::Client));
        assert_filtered(&filtered, &flags, "client-flag", false);
        assert_filtered(&filtered, &flags, "server-flag", true);
        assert_filtered(&filtered, &flags, "all-flag", false);
    }

    #[test]
    fn test_runtime_filtering_takes_precedence_over_flag_keys() {
        let all_flags = vec![
            flag(1, "client-only-flag", Some("client"), None),
            flag(2, "server-only-flag", Some("server"), None),
            flag(3, "all-flag", Some("all"), None),
            flag(4, "no-runtime-flag", None, None),
        ];

        let client_filtered =
            collect_excluded_by_runtime(&all_flags, Some(EvaluationRuntime::Client));
        assert_filtered(&client_filtered, &all_flags, "client-only-flag", false);
        assert_filtered(&client_filtered, &all_flags, "server-only-flag", true);
        assert_filtered(&client_filtered, &all_flags, "all-flag", false);
        assert_filtered(&client_filtered, &all_flags, "no-runtime-flag", false);

        let server_filtered =
            collect_excluded_by_runtime(&all_flags, Some(EvaluationRuntime::Server));
        assert_filtered(&server_filtered, &all_flags, "client-only-flag", true);
        assert_filtered(&server_filtered, &all_flags, "server-only-flag", false);
        assert_filtered(&server_filtered, &all_flags, "all-flag", false);
        assert_filtered(&server_filtered, &all_flags, "no-runtime-flag", false);
    }

    #[test]
    fn test_collect_excluded_by_tags_no_environment_tags() {
        let flags = vec![
            flag(1, "flag1", None, None),
            flag(2, "flag2", None, Some(vec!["app".to_string()])),
            flag(
                3,
                "flag3",
                None,
                Some(vec!["docs".to_string(), "marketing".to_string()]),
            ),
        ];

        assert!(collect_excluded_by_tags(&flags, None).is_empty());
        assert!(collect_excluded_by_tags(&flags, Some(&vec![])).is_empty());
    }

    #[test]
    fn test_collect_excluded_by_tags_with_matching_tags() {
        let flags = vec![
            flag(1, "no-tags", None, None),
            flag(2, "app-only", None, Some(vec!["app".to_string()])),
            flag(3, "docs-only", None, Some(vec!["docs".to_string()])),
            flag(
                4,
                "multi-env",
                None,
                Some(vec!["app".to_string(), "docs".to_string()]),
            ),
        ];

        // "app" environment — docs-only filtered out
        let app_env = vec!["app".to_string()];
        let filtered = collect_excluded_by_tags(&flags, Some(&app_env));
        assert_filtered(&filtered, &flags, "no-tags", false);
        assert_filtered(&filtered, &flags, "app-only", false);
        assert_filtered(&filtered, &flags, "docs-only", true);
        assert_filtered(&filtered, &flags, "multi-env", false);

        // "docs" environment — app-only filtered out
        let docs_env = vec!["docs".to_string()];
        let filtered = collect_excluded_by_tags(&flags, Some(&docs_env));
        assert_filtered(&filtered, &flags, "no-tags", false);
        assert_filtered(&filtered, &flags, "app-only", true);
        assert_filtered(&filtered, &flags, "docs-only", false);
        assert_filtered(&filtered, &flags, "multi-env", false);
    }

    #[test]
    fn test_collect_excluded_by_tags_no_matching_tags() {
        let flags = vec![
            flag(1, "app-only", None, Some(vec!["app".to_string()])),
            flag(2, "docs-only", None, Some(vec!["docs".to_string()])),
        ];

        let marketing_env = vec!["marketing".to_string()];
        let filtered = collect_excluded_by_tags(&flags, Some(&marketing_env));
        assert_filtered(&filtered, &flags, "app-only", true);
        assert_filtered(&filtered, &flags, "docs-only", true);
    }

    #[test]
    fn test_collect_excluded_by_tags_empty_flag_tags() {
        let flags = vec![
            flag(1, "empty-tags", None, Some(vec![])),
            flag(2, "app-only", None, Some(vec!["app".to_string()])),
        ];

        let app_env = vec!["app".to_string()];
        let filtered = collect_excluded_by_tags(&flags, Some(&app_env));
        assert_filtered(&filtered, &flags, "empty-tags", false);
        assert_filtered(&filtered, &flags, "app-only", false);
    }

    #[test]
    fn test_collect_excluded_by_tags_multiple_environment_tags() {
        let flags = vec![
            flag(1, "app-only", None, Some(vec!["app".to_string()])),
            flag(2, "docs-only", None, Some(vec!["docs".to_string()])),
            flag(
                3,
                "marketing-only",
                None,
                Some(vec!["marketing".to_string()]),
            ),
            flag(4, "no-tags", None, None),
        ];

        let multi_env = vec!["app".to_string(), "docs".to_string()];
        let filtered = collect_excluded_by_tags(&flags, Some(&multi_env));
        assert_filtered(&filtered, &flags, "app-only", false);
        assert_filtered(&filtered, &flags, "docs-only", false);
        assert_filtered(&filtered, &flags, "marketing-only", true);
        assert_filtered(&filtered, &flags, "no-tags", false);
    }

    #[test]
    fn test_runtime_and_tag_filtering_stacks() {
        let flags = vec![
            flag(
                1,
                "server-app",
                Some("server"),
                Some(vec!["app".to_string()]),
            ),
            flag(
                2,
                "client-app",
                Some("client"),
                Some(vec!["app".to_string()]),
            ),
            flag(
                3,
                "server-docs",
                Some("server"),
                Some(vec!["docs".to_string()]),
            ),
        ];

        let mut combined = collect_excluded_by_runtime(&flags, Some(EvaluationRuntime::Server));
        let app_env = vec!["app".to_string()];
        combined.extend(collect_excluded_by_tags(&flags, Some(&app_env)));

        assert_filtered(&combined, &flags, "server-app", false);
        assert_filtered(&combined, &flags, "client-app", true);
        assert_filtered(&combined, &flags, "server-docs", true);
    }

    #[test]
    fn test_all_flags_filtered_after_runtime_mismatch() {
        let flags = vec![
            flag(1, "client-only", Some("client"), None),
            flag(2, "also-client", Some("client"), None),
        ];

        let filtered = collect_excluded_by_runtime(&flags, Some(EvaluationRuntime::Server));
        assert_eq!(
            filtered.len(),
            2,
            "All client-only flags should be filtered when requesting server runtime"
        );
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

    fn override_payload(id: i32, team_id: i32, key: &str) -> Value {
        serde_json::json!({
            "id": id,
            "team_id": team_id,
            "name": null,
            "key": key,
            "filters": { "groups": [{"properties": [], "rollout_percentage": 50}] },
            "deleted": false,
            "active": true,
        })
    }

    fn flag_with_team(id: i32, team_id: i32, key: &str) -> FeatureFlag {
        mock!(FeatureFlag,
            id: id,
            team_id: team_id,
            key: key.mock_into()
        )
    }

    #[test]
    fn test_apply_flag_overrides_matching_identity_applies() {
        let mut flags = vec![flag_with_team(1, 100, "my-flag")];
        let mut overrides = HashMap::new();
        overrides.insert("my-flag".to_string(), override_payload(1, 100, "my-flag"));

        let applied = apply_flag_overrides(&mut flags, &overrides);

        assert_eq!(applied, vec!["my-flag".to_string()]);
        assert_eq!(flags[0].filters.groups[0].rollout_percentage, Some(50.0));
    }

    #[test]
    fn test_apply_flag_overrides_rejects_team_id_mismatch() {
        let mut flags = vec![flag_with_team(1, 100, "my-flag")];
        let mut overrides = HashMap::new();
        // Override claims to belong to team 999 — must be rejected to stop a
        // caller from swapping in another team's identity.
        overrides.insert("my-flag".to_string(), override_payload(1, 999, "my-flag"));

        let applied = apply_flag_overrides(&mut flags, &overrides);

        assert!(applied.is_empty(), "mismatched team_id must not be applied");
        assert_eq!(flags[0].team_id, 100, "original team_id must be preserved");
    }

    #[test]
    fn test_apply_flag_overrides_rejects_id_mismatch() {
        let mut flags = vec![flag_with_team(1, 100, "my-flag")];
        let mut overrides = HashMap::new();
        overrides.insert("my-flag".to_string(), override_payload(999, 100, "my-flag"));

        let applied = apply_flag_overrides(&mut flags, &overrides);

        assert!(applied.is_empty(), "mismatched id must not be applied");
        assert_eq!(flags[0].id, 1, "original id must be preserved");
    }

    #[test]
    fn test_apply_flag_overrides_rejects_key_mismatch() {
        let mut flags = vec![flag_with_team(1, 100, "my-flag")];
        let mut overrides = HashMap::new();
        // The map is keyed by "my-flag" but the payload's embedded key is
        // different — reject to keep the keying contract honest.
        overrides.insert(
            "my-flag".to_string(),
            override_payload(1, 100, "other-flag"),
        );

        let applied = apply_flag_overrides(&mut flags, &overrides);

        assert!(applied.is_empty(), "mismatched key must not be applied");
    }

    #[test]
    fn test_apply_flag_overrides_skips_unknown_keys() {
        let mut flags = vec![flag_with_team(1, 100, "my-flag")];
        let mut overrides = HashMap::new();
        overrides.insert(
            "not-in-list".to_string(),
            override_payload(1, 100, "not-in-list"),
        );

        let applied = apply_flag_overrides(&mut flags, &overrides);

        assert!(applied.is_empty());
    }
}
