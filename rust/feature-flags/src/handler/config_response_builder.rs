use crate::{
    api::{
        errors::FlagError,
        types::{ConfigResponse, FlagsResponse},
    },
    config_cache::get_cached_config,
    team::team_models::Team,
};
use limiters::redis::QuotaResource;
use serde_json::{json, Value};

use super::types::RequestContext;

/// Build response by passing through cached config from Python's HyperCache.
///
/// The config blob is passed through as-is without interpretation.
/// Only session recording quota limiting is applied in Rust.
pub async fn build_response_from_cache(
    flags_response: FlagsResponse,
    context: &RequestContext,
    team: &Team,
) -> Result<FlagsResponse, FlagError> {
    let mut response = flags_response;

    if !context.meta.config.unwrap_or(false) {
        return Ok(response);
    }

    let cached_config = get_cached_config(&context.state.config_hypercache_reader, &team.api_token)
        .await?
        .ok_or_else(|| {
            FlagError::Internal(format!(
                "Config cache miss for team {} - Python has not populated the cache",
                team.id
            ))
        })?;

    let is_recordings_limited = if context.state.config.flags_session_replay_quota_check {
        context
            .state
            .session_replay_billing_limiter
            .is_limited(&team.api_token)
            .await
    } else {
        false
    };

    response.config = ConfigResponse::from_value(cached_config.clone());

    if is_recordings_limited {
        apply_recordings_quota_limit(&mut response, &cached_config);
    } else if let Some(quota_limited) = cached_config.get("quotaLimited") {
        if let Some(arr) = quota_limited.as_array() {
            response.quota_limited = Some(
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect(),
            );
        }
    }

    tracing::debug!(
        team_id = team.id,
        "Passed through cached config from HyperCache"
    );

    Ok(response)
}

/// Apply session recording quota limit by disabling recording and updating quotaLimited.
fn apply_recordings_quota_limit(response: &mut FlagsResponse, cached_config: &Value) {
    response.config.set("sessionRecording", json!(false));

    let mut limited: Vec<String> = cached_config
        .get("quotaLimited")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();

    let recordings_str = QuotaResource::Recordings.as_str().to_string();
    if !limited.contains(&recordings_str) {
        limited.push(recordings_str);
    }
    response.quota_limited = Some(limited);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use uuid::Uuid as StdUuid;

    fn create_base_team() -> Team {
        Team {
            id: 1,
            name: "Test Team".to_string(),
            api_token: "test-token".to_string(),
            uuid: Uuid::new_v4(),
            organization_id: None,
            autocapture_opt_out: None,
            autocapture_exceptions_opt_in: None,
            autocapture_web_vitals_opt_in: None,
            capture_performance_opt_in: None,
            capture_console_log_opt_in: None,
            logs_settings: None,
            session_recording_opt_in: false,
            inject_web_apps: None,
            surveys_opt_in: None,
            heatmaps_opt_in: None,
            conversations_enabled: None,
            conversations_settings: None,
            capture_dead_clicks: None,
            flags_persistence_default: None,
            session_recording_sample_rate: None,
            session_recording_minimum_duration_milliseconds: None,
            autocapture_web_vitals_allowed_metrics: None,
            autocapture_exceptions_errors_to_ignore: None,
            session_recording_linked_flag: None,
            session_recording_network_payload_capture_config: None,
            session_recording_masking_config: None,
            session_replay_config: None,
            survey_config: None,
            extra_settings: None,
            session_recording_url_trigger_config: None,
            session_recording_url_blocklist_config: None,
            session_recording_event_trigger_config: None,
            session_recording_trigger_match_type_config: None,
            recording_domains: None,
            cookieless_server_hash_mode: Some(0),
            timezone: "UTC".to_string(),
        }
    }

    fn create_base_response() -> FlagsResponse {
        FlagsResponse::new(false, HashMap::new(), None, Uuid::new_v4())
    }

    #[test]
    fn test_apply_recordings_quota_limit_adds_to_empty() {
        let mut response = create_base_response();
        let cached = json!({});
        apply_recordings_quota_limit(&mut response, &cached);

        assert_eq!(response.config.get("sessionRecording"), Some(&json!(false)));
        assert_eq!(response.quota_limited, Some(vec!["recordings".to_string()]));
    }

    #[test]
    fn test_apply_recordings_quota_limit_merges_existing() {
        let mut response = create_base_response();
        let cached = json!({"quotaLimited": ["feature_flags"]});
        apply_recordings_quota_limit(&mut response, &cached);

        assert_eq!(
            response.quota_limited,
            Some(vec!["feature_flags".to_string(), "recordings".to_string()])
        );
    }

    #[test]
    fn test_apply_recordings_quota_limit_no_duplicate() {
        let mut response = create_base_response();
        let cached = json!({"quotaLimited": ["recordings"]});
        apply_recordings_quota_limit(&mut response, &cached);

        assert_eq!(response.quota_limited, Some(vec!["recordings".to_string()]));
    }

    #[test]
    fn test_analytics_config_disabled_excluded_team() {
        let mut config = Config::default_test_config();
        config.debug = FlexBool(false);
        config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::All; // All means exclude all teams

        let mut response = create_base_response();
        let team = create_base_team(); // team.id = 1

        apply_core_config_fields(&mut response, &config, &team);

        assert!(response.config.analytics.is_none());
    }

    #[test]
    fn test_analytics_config_disabled_empty_endpoint() {
        let mut config = Config::default_test_config();
        config.debug = FlexBool(false);
        config.new_analytics_capture_endpoint = "".to_string(); // Empty endpoint
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::None; // None means exclude nobody

        let mut response = create_base_response();
        let team = create_base_team();

        apply_core_config_fields(&mut response, &config, &team);

        assert!(response.config.analytics.is_none());
    }

    #[test]
    fn test_elements_chain_as_string_enabled() {
        let mut config = Config::default_test_config();
        config.element_chain_as_string_excluded_teams = TeamIdCollection::None; // None means exclude nobody

        let mut response = create_base_response();
        let team = create_base_team();

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.elements_chain_as_string, Some(true));
    }

    #[test]
    fn test_elements_chain_as_string_excluded() {
        let mut config = Config::default_test_config();
        config.element_chain_as_string_excluded_teams = TeamIdCollection::All; // All means exclude all teams

        let mut response = create_base_response();
        let team = create_base_team(); // team.id = 1

        apply_core_config_fields(&mut response, &config, &team);

        assert!(response.config.elements_chain_as_string.is_none());
    }

    #[test]
    fn test_capture_performance_both_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_performance_opt_in = Some(false);
        team.autocapture_web_vitals_opt_in = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.capture_performance, Some(json!(false)));
    }

    #[test]
    fn test_capture_performance_network_only() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_performance_opt_in = Some(true);
        team.autocapture_web_vitals_opt_in = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        let expected = json!({
            "network_timing": true,
            "web_vitals": false,
            "web_vitals_allowed_metrics": null
        });
        assert_eq!(response.config.capture_performance, Some(expected));
    }

    #[test]
    fn test_capture_performance_web_vitals_only() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_performance_opt_in = Some(false);
        team.autocapture_web_vitals_opt_in = Some(true);

        apply_core_config_fields(&mut response, &config, &team);

        let expected = json!({
            "network_timing": false,
            "web_vitals": true,
            "web_vitals_allowed_metrics": null
        });
        assert_eq!(response.config.capture_performance, Some(expected));
    }

    #[test]
    fn test_capture_performance_both_enabled_with_metrics() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_performance_opt_in = Some(true);
        team.autocapture_web_vitals_opt_in = Some(true);
        team.autocapture_web_vitals_allowed_metrics = Some(Json(json!(["CLS", "FCP", "LCP"])));

        apply_core_config_fields(&mut response, &config, &team);

        let expected = json!({
            "network_timing": true,
            "web_vitals": true,
            "web_vitals_allowed_metrics": ["CLS", "FCP", "LCP"]
        });
        assert_eq!(response.config.capture_performance, Some(expected));
    }

    #[test]
    fn test_autocapture_exceptions_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.autocapture_exceptions_opt_in = Some(true);

        apply_core_config_fields(&mut response, &config, &team);

        let expected = json!({"endpoint": "/e/"});
        assert_eq!(response.config.autocapture_exceptions, Some(expected));
    }

    #[test]
    fn test_autocapture_exceptions_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.autocapture_exceptions_opt_in = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.autocapture_exceptions, Some(json!(false)));
    }

    #[test]
    fn test_autocapture_exceptions_none() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let team = create_base_team(); // autocapture_exceptions_opt_in is None

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.autocapture_exceptions, Some(json!(false)));
    }

    #[test]
    fn test_surveys_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.surveys_opt_in = Some(true);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.surveys, Some(json!(true)));
    }

    #[test]
    fn test_surveys_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.surveys_opt_in = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.surveys, Some(json!(false)));
    }

    #[test]
    fn test_heatmaps_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.heatmaps_opt_in = Some(true);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.heatmaps, Some(true));
    }

    #[test]
    fn test_heatmaps_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.heatmaps_opt_in = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.heatmaps, Some(false));
    }

    #[test]
    fn test_flags_persistence_default_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.flags_persistence_default = Some(true);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.flags_persistence_default, Some(true));
    }

    #[test]
    fn test_flags_persistence_default_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.flags_persistence_default = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.flags_persistence_default, Some(false));
    }

    #[test]
    fn test_autocapture_opt_out_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.autocapture_opt_out = Some(true);

        apply_core_config_fields(&mut response, &config, &team);

        assert!(response.config.autocapture_opt_out.unwrap());
    }

    #[test]
    fn test_autocapture_opt_out_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.autocapture_opt_out = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        assert!(!response.config.autocapture_opt_out.unwrap());
    }

    #[test]
    fn test_capture_dead_clicks_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_dead_clicks = Some(true);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.capture_dead_clicks, Some(true));
    }

    #[test]
    fn test_capture_dead_clicks_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_dead_clicks = Some(false);

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(response.config.capture_dead_clicks, Some(false));
    }

    #[test]
    fn test_all_optional_fields_none() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let team = create_base_team(); // all optional fields are None/false

        apply_core_config_fields(&mut response, &config, &team);

        tracing::debug!("response: {:?}", response);

        // Test that defaults are applied correctly
        assert_eq!(response.config.surveys, Some(json!(false)));
        assert_eq!(response.config.heatmaps, Some(false));
        assert_eq!(response.config.flags_persistence_default, Some(false));
        assert_eq!(response.config.autocapture_exceptions, Some(json!(false)));
        assert_eq!(response.config.capture_performance, Some(json!(false)));
        assert!(!response.config.autocapture_opt_out.unwrap());
        assert!(response.config.capture_dead_clicks.is_none());
    }

    #[test]
    fn test_team_exclusion_all_teams() {
        let mut config = Config::default_test_config();
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::All; // All means exclude all teams
        config.element_chain_as_string_excluded_teams = TeamIdCollection::All; // All means exclude all teams

        let mut response = create_base_response();
        let team = create_base_team();

        apply_core_config_fields(&mut response, &config, &team);

        // Both should be disabled/None for excluded teams
        assert!(response.config.analytics.is_none());
        assert!(response.config.elements_chain_as_string.is_none());
    }

    #[test]
    fn test_team_exclusion_specific_teams() {
        let mut config = Config::default_test_config();
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::TeamIds(vec![1, 3, 4]); // team 1 is in list, so excluded
        config.element_chain_as_string_excluded_teams = TeamIdCollection::TeamIds(vec![1, 3, 4]); // team 1 is in list, so excluded
        config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();

        let mut response = create_base_response();
        let team = create_base_team(); // team.id = 1

        apply_core_config_fields(&mut response, &config, &team);

        // Both should be disabled/None for team id 1 (in exclusion list)
        assert!(response.config.analytics.is_none());
        assert!(response.config.elements_chain_as_string.is_none());
    }

    #[test]
    fn test_team_not_in_exclusion_list() {
        let mut config = Config::default_test_config();
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::None; // None means exclude nobody
        config.element_chain_as_string_excluded_teams = TeamIdCollection::None; // None means exclude nobody
        config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();

        let mut response = create_base_response();
        let team = create_base_team(); // team.id = 1

        apply_core_config_fields(&mut response, &config, &team);

        // Both should be enabled for team id 1 (not in exclusion list)
        assert!(response.config.analytics.is_some());
        assert_eq!(response.config.elements_chain_as_string, Some(true));
    }

    #[test]
    fn test_session_recording_disabled() {
        let mut team = create_base_team();
        team.session_recording_opt_in = false; // Disabled

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers);

        // Should return disabled=false when session recording is off
        if let Some(SessionRecordingField::Disabled(enabled)) = result {
            assert!(!enabled);
        } else {
            panic!("Expected SessionRecordingField::Disabled(false)");
        }
    }

    #[test]
    fn test_session_recording_enabled_no_rrweb_script() {
        let mut team = create_base_team();
        team.session_recording_opt_in = true; // Enabled

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers);

        // Should return config with no script_config since rrweb script is not configured
        if let Some(SessionRecordingField::Config(config)) = result {
            assert_eq!(config.endpoint, Some("/s/".to_string()));
            assert_eq!(config.recorder_version, Some("v2".to_string()));
            assert!(config.script_config.is_none()); // No script config
        } else {
            panic!("Expected SessionRecordingField::Config");
        }
    }

    #[test]
    fn test_session_recording_empty_domains_allowed() {
        let mut team = create_base_team();
        team.session_recording_opt_in = true;
        team.recording_domains = Some(vec![]); // Empty domains list

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers);

        // Should return config (enabled) when recording_domains is empty list
        if let Some(SessionRecordingField::Config(_)) = result {
            // Test passes if we reach this point
        } else {
            panic!("Expected SessionRecordingField::Config when recording_domains is empty list");
        }
    }

    #[test]
    fn test_session_recording_no_domains_allowed() {
        let mut team = create_base_team();
        team.session_recording_opt_in = true;
        team.recording_domains = None; // No domains list

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers);

        // Should return config (enabled) when recording_domains is empty list
        if let Some(SessionRecordingField::Config(_)) = result {
            // Test passes if we reach this point
        } else {
            panic!("Expected SessionRecordingField::Config when recording_domains is empty list");
        }
    }

    #[test]
    fn test_extra_settings_not_exposed_in_response() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.extra_settings = Some(Json(json!({"internal_config": {"nested": "data"}})));

        apply_core_config_fields(&mut response, &config, &team);

        let serialized = serde_json::to_string(&response).expect("Failed to serialize response");
        assert!(
            !serialized.contains("extra_settings"),
            "Response should not contain extra_settings field"
        );
    }

    #[test]
    fn test_logs_config_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.logs_settings = Some(Json(json!({"capture_console_logs": true})));

        apply_core_config_fields(&mut response, &config, &team);

        assert_eq!(
            config.get("supportedCompression"),
            Some(&json!(["gzip", "gzip-js"]))
        );
        assert_eq!(config.get("heatmaps"), Some(&json!(true)));
        assert_eq!(
            config.get("someNewField"),
            Some(&json!("that rust doesn't know about"))
        );
        assert_eq!(
            config.get("nested"),
            Some(&json!({"deeply": {"value": 123}}))
        );
    }
}
