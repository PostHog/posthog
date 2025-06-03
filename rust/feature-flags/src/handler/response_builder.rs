use crate::{
    api::{
        errors::FlagError,
        types::{AnalyticsConfig, FlagsResponse},
    },
    config::Config,
    site_apps::get_decide_site_apps,
    team::team_models::Team,
};
use axum::http::HeaderMap;
use std::{collections::HashMap, sync::Arc};

use super::{session_recording, types::RequestContext};

pub struct ConfigContext {
    pub config: Config,
    pub reader: Arc<dyn common_database::Client + Send + Sync>,
    pub redis: Arc<dyn common_redis::Client + Send + Sync>,
    pub headers: HeaderMap,
}

impl ConfigContext {
    pub fn from_request_context(context: &RequestContext) -> Self {
        Self {
            config: context.state.config.clone(),
            reader: context.state.reader.clone(),
            redis: context.state.redis.clone(),
            headers: context.headers.clone(),
        }
    }

    /// This constructor allows you to create a ConfigContext without going through
    /// the full RequestContext, which is useful for testing config field logic
    /// in isolation.
    pub fn new(
        config: Config,
        reader: Arc<dyn common_database::Client + Send + Sync>,
        redis: Arc<dyn common_redis::Client + Send + Sync>,
        headers: HeaderMap,
    ) -> Self {
        Self {
            config,
            reader,
            redis,
            headers,
        }
    }
}

pub async fn build_response(
    flags_response: FlagsResponse,
    context: &RequestContext,
    team: &Team,
) -> Result<FlagsResponse, FlagError> {
    let mut response = flags_response;

    if context.meta.config.unwrap_or(false) {
        let config_context = ConfigContext::from_request_context(context);
        apply_config_fields(&mut response, &config_context, team).await?;
    }

    Ok(response)
}

async fn apply_config_fields(
    response: &mut FlagsResponse,
    context: &ConfigContext,
    team: &Team,
) -> Result<(), FlagError> {
    let capture_web_vitals = team.autocapture_web_vitals_opt_in.unwrap_or(false);
    let autocapture_web_vitals_allowed_metrics =
        team.autocapture_web_vitals_allowed_metrics.as_ref();
    let capture_network_timing = team.capture_performance_opt_in.unwrap_or(false);

    response.config.has_feature_flags = Some(!response.flags.is_empty());
    response.config.supported_compression = vec!["gzip".to_string(), "gzip-js".to_string()];
    response.config.autocapture_opt_out = team.autocapture_opt_out;

    response.config.analytics = if !context.config.debug.0
        && !context.config.is_team_excluded(
            team.id,
            &context.config.new_analytics_capture_excluded_team_ids,
        ) {
        Some(AnalyticsConfig {
            endpoint: Some(context.config.new_analytics_capture_endpoint.clone()),
        })
    } else {
        None
    };

    response.config.elements_chain_as_string = if !context.config.is_team_excluded(
        team.id,
        &context.config.element_chain_as_string_excluded_teams,
    ) {
        Some(true)
    } else {
        None
    };

    response.config.capture_performance = match (capture_network_timing, capture_web_vitals) {
        (false, false) => Some(serde_json::json!(false)),
        (network, web_vitals) => {
            let mut perf_map = HashMap::new();
            perf_map.insert("network_timing".to_string(), serde_json::json!(network));
            perf_map.insert("web_vitals".to_string(), serde_json::json!(web_vitals));
            if web_vitals {
                perf_map.insert(
                    "web_vitals_allowed_metrics".to_string(),
                    serde_json::json!(autocapture_web_vitals_allowed_metrics.cloned()),
                );
            }
            Some(serde_json::json!(perf_map))
        }
    };

    response.config.config = Some(serde_json::json!({"enable_collect_everything": true}));

    response.config.autocapture_exceptions = if team.autocapture_exceptions_opt_in.unwrap_or(false)
    {
        Some(serde_json::json!(HashMap::from([(
            "endpoint".to_string(),
            serde_json::json!("/e/")
        )])))
    } else {
        Some(serde_json::json!(false))
    };

    response.config.surveys = Some(serde_json::json!(team.surveys_opt_in.unwrap_or(false)));
    response.config.heatmaps = Some(team.heatmaps_opt_in.unwrap_or(false));
    response.config.default_identified_only = Some(true);
    response.config.flags_persistence_default =
        Some(team.flags_persistence_default.unwrap_or(false));
    response.config.session_recording = session_recording::session_recording_config_response(
        team,
        &context.headers,
        &context.config,
    );
    response.config.toolbar_params = Some(serde_json::json!(
        HashMap::<String, serde_json::Value>::new()
    ));
    response.config.is_authenticated = Some(false);
    response.config.capture_dead_clicks = team.capture_dead_clicks;

    response.config.site_apps = if team.inject_web_apps.unwrap_or(false) {
        Some(get_decide_site_apps(context.reader.clone(), team.id).await?)
    } else {
        Some(vec![])
    };

    Ok(())
}

#[cfg(test)]
mod tests {
    use crate::{
        api::types::{
            AnalyticsConfig, ConfigResponse, FlagDetails, FlagDetailsMetadata,
            FlagEvaluationReason, FlagsResponse, SessionRecordingField,
        },
        config::{Config, FlexBool, TeamIdCollection},
        handler::session_recording,
        team::team_models::Team,
    };
    use serde_json::json;
    use sqlx::types::{Json, Uuid};
    use std::collections::HashMap;
    use uuid::Uuid as StdUuid;

    // Test-only function that tests config logic without database dependencies
    fn apply_config_fields_test_only(response: &mut FlagsResponse, config: &Config, team: &Team) {
        let capture_web_vitals = team.autocapture_web_vitals_opt_in.unwrap_or(false);
        let autocapture_web_vitals_allowed_metrics =
            team.autocapture_web_vitals_allowed_metrics.as_ref();
        let capture_network_timing = team.capture_performance_opt_in.unwrap_or(false);

        response.config.has_feature_flags = Some(!response.flags.is_empty());
        response.config.supported_compression = vec!["gzip".to_string(), "gzip-js".to_string()];
        response.config.autocapture_opt_out = team.autocapture_opt_out;

        response.config.analytics = if !config.debug.0
            && !config.is_team_excluded(team.id, &config.new_analytics_capture_excluded_team_ids)
        {
            Some(AnalyticsConfig {
                endpoint: Some(config.new_analytics_capture_endpoint.clone()),
            })
        } else {
            None
        };

        response.config.elements_chain_as_string =
            if !config.is_team_excluded(team.id, &config.element_chain_as_string_excluded_teams) {
                Some(true)
            } else {
                None
            };

        response.config.capture_performance = match (capture_network_timing, capture_web_vitals) {
            (false, false) => Some(serde_json::json!(false)),
            (network, web_vitals) => {
                let mut perf_map = HashMap::new();
                perf_map.insert("network_timing".to_string(), serde_json::json!(network));
                perf_map.insert("web_vitals".to_string(), serde_json::json!(web_vitals));
                if web_vitals {
                    perf_map.insert(
                        "web_vitals_allowed_metrics".to_string(),
                        serde_json::json!(autocapture_web_vitals_allowed_metrics.cloned()),
                    );
                }
                Some(serde_json::json!(perf_map))
            }
        };

        response.config.config = Some(serde_json::json!({"enable_collect_everything": true}));

        response.config.autocapture_exceptions =
            if team.autocapture_exceptions_opt_in.unwrap_or(false) {
                Some(serde_json::json!(HashMap::from([(
                    "endpoint".to_string(),
                    serde_json::json!("/e/")
                )])))
            } else {
                Some(serde_json::json!(false))
            };

        response.config.surveys = Some(serde_json::json!(team.surveys_opt_in.unwrap_or(false)));
        response.config.heatmaps = Some(team.heatmaps_opt_in.unwrap_or(false));
        response.config.default_identified_only = Some(true);
        response.config.flags_persistence_default =
            Some(team.flags_persistence_default.unwrap_or(false));
        response.config.toolbar_params = Some(serde_json::json!(HashMap::<
            String,
            serde_json::Value,
        >::new()));
        response.config.is_authenticated = Some(false);
        response.config.capture_dead_clicks = team.capture_dead_clicks;

        // Skip site_apps and session_recording since they require database/headers
        // NB: I test this behavior thoroughly in site_apps/mod.rs
        response.config.site_apps = Some(vec![]);
    }

    fn create_base_team() -> Team {
        Team {
            id: 1,
            name: "Test Team".to_string(),
            api_token: "test-token".to_string(),
            project_id: 1,
            uuid: Uuid::new_v4(),
            autocapture_opt_out: None,
            autocapture_exceptions_opt_in: None,
            autocapture_web_vitals_opt_in: None,
            capture_performance_opt_in: None,
            capture_console_log_opt_in: None,
            session_recording_opt_in: false,
            inject_web_apps: None,
            surveys_opt_in: None,
            heatmaps_opt_in: None,
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
            session_recording_url_trigger_config: None,
            session_recording_url_blocklist_config: None,
            session_recording_event_trigger_config: None,
            session_recording_trigger_match_type_config: None,
            recording_domains: None,
            cookieless_server_hash_mode: 0,
            timezone: "UTC".to_string(),
        }
    }

    fn create_base_response() -> FlagsResponse {
        FlagsResponse {
            errors_while_computing_flags: false,
            flags: HashMap::new(),
            quota_limited: None,
            request_id: StdUuid::new_v4(),
            config: ConfigResponse::default(),
        }
    }

    #[test]
    fn test_basic_config_fields() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let team = create_base_team();

        apply_config_fields_test_only(&mut response, &config, &team);

        // Basic fields always set
        assert_eq!(
            response.config.supported_compression,
            vec!["gzip", "gzip-js"]
        );
        assert_eq!(response.config.has_feature_flags, Some(false)); // empty flags
        assert_eq!(response.config.default_identified_only, Some(true));
        assert_eq!(response.config.is_authenticated, Some(false));
        assert_eq!(
            response.config.config,
            Some(json!({"enable_collect_everything": true}))
        );
        assert_eq!(response.config.toolbar_params, Some(json!({})));
    }

    #[test]
    fn test_has_feature_flags_with_flags() {
        let mut response = create_base_response();
        response.flags.insert(
            "test_flag".to_string(),
            FlagDetails {
                key: "test_flag".to_string(),
                enabled: true,
                variant: None,
                reason: FlagEvaluationReason {
                    code: "condition_match".to_string(),
                    condition_index: Some(0),
                    description: None,
                },
                metadata: FlagDetailsMetadata {
                    id: 1,
                    version: 1,
                    description: None,
                    payload: None,
                },
            },
        );

        let config = Config::default_test_config();
        let team = create_base_team();

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.has_feature_flags, Some(true));
    }

    #[test]
    fn test_analytics_config_enabled() {
        let mut config = Config::default_test_config();
        config.debug = FlexBool(false);
        config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::None; // None means exclude nobody

        let mut response = create_base_response();
        let team = create_base_team();

        apply_config_fields_test_only(&mut response, &config, &team);

        assert!(response.config.analytics.is_some());
        assert_eq!(
            response.config.analytics.unwrap().endpoint,
            Some("https://analytics.posthog.com".to_string())
        );
    }

    #[test]
    fn test_analytics_config_disabled_debug_mode() {
        let mut config = Config::default_test_config();
        config.debug = FlexBool(true);
        config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();

        let mut response = create_base_response();
        let team = create_base_team();

        apply_config_fields_test_only(&mut response, &config, &team);

        assert!(response.config.analytics.is_none());
    }

    #[test]
    fn test_analytics_config_disabled_excluded_team() {
        let mut config = Config::default_test_config();
        config.debug = FlexBool(false);
        config.new_analytics_capture_endpoint = "https://analytics.posthog.com".to_string();
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::All; // All means exclude all teams

        let mut response = create_base_response();
        let team = create_base_team(); // team.id = 1

        apply_config_fields_test_only(&mut response, &config, &team);

        assert!(response.config.analytics.is_none());
    }

    #[test]
    fn test_elements_chain_as_string_enabled() {
        let mut config = Config::default_test_config();
        config.element_chain_as_string_excluded_teams = TeamIdCollection::None; // None means exclude nobody

        let mut response = create_base_response();
        let team = create_base_team();

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.elements_chain_as_string, Some(true));
    }

    #[test]
    fn test_elements_chain_as_string_excluded() {
        let mut config = Config::default_test_config();
        config.element_chain_as_string_excluded_teams = TeamIdCollection::All; // All means exclude all teams

        let mut response = create_base_response();
        let team = create_base_team(); // team.id = 1

        apply_config_fields_test_only(&mut response, &config, &team);

        assert!(response.config.elements_chain_as_string.is_none());
    }

    #[test]
    fn test_capture_performance_both_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_performance_opt_in = Some(false);
        team.autocapture_web_vitals_opt_in = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.capture_performance, Some(json!(false)));
    }

    #[test]
    fn test_capture_performance_network_only() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_performance_opt_in = Some(true);
        team.autocapture_web_vitals_opt_in = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        let expected = json!({
            "network_timing": true,
            "web_vitals": false
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

        apply_config_fields_test_only(&mut response, &config, &team);

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

        apply_config_fields_test_only(&mut response, &config, &team);

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

        apply_config_fields_test_only(&mut response, &config, &team);

        let expected = json!({"endpoint": "/e/"});
        assert_eq!(response.config.autocapture_exceptions, Some(expected));
    }

    #[test]
    fn test_autocapture_exceptions_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.autocapture_exceptions_opt_in = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.autocapture_exceptions, Some(json!(false)));
    }

    #[test]
    fn test_autocapture_exceptions_none() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let team = create_base_team(); // autocapture_exceptions_opt_in is None

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.autocapture_exceptions, Some(json!(false)));
    }

    #[test]
    fn test_surveys_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.surveys_opt_in = Some(true);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.surveys, Some(json!(true)));
    }

    #[test]
    fn test_surveys_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.surveys_opt_in = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.surveys, Some(json!(false)));
    }

    #[test]
    fn test_heatmaps_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.heatmaps_opt_in = Some(true);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.heatmaps, Some(true));
    }

    #[test]
    fn test_heatmaps_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.heatmaps_opt_in = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.heatmaps, Some(false));
    }

    #[test]
    fn test_flags_persistence_default_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.flags_persistence_default = Some(true);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.flags_persistence_default, Some(true));
    }

    #[test]
    fn test_flags_persistence_default_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.flags_persistence_default = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.flags_persistence_default, Some(false));
    }

    #[test]
    fn test_autocapture_opt_out_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.autocapture_opt_out = Some(true);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.autocapture_opt_out, Some(true));
    }

    #[test]
    fn test_autocapture_opt_out_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.autocapture_opt_out = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.autocapture_opt_out, Some(false));
    }

    #[test]
    fn test_capture_dead_clicks_enabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_dead_clicks = Some(true);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.capture_dead_clicks, Some(true));
    }

    #[test]
    fn test_capture_dead_clicks_disabled() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let mut team = create_base_team();

        team.capture_dead_clicks = Some(false);

        apply_config_fields_test_only(&mut response, &config, &team);

        assert_eq!(response.config.capture_dead_clicks, Some(false));
    }

    #[test]
    fn test_all_optional_fields_none() {
        let mut response = create_base_response();
        let config = Config::default_test_config();
        let team = create_base_team(); // all optional fields are None/false

        apply_config_fields_test_only(&mut response, &config, &team);

        // Test that defaults are applied correctly
        assert_eq!(response.config.surveys, Some(json!(false)));
        assert_eq!(response.config.heatmaps, Some(false));
        assert_eq!(response.config.flags_persistence_default, Some(false));
        assert_eq!(response.config.autocapture_exceptions, Some(json!(false)));
        assert_eq!(response.config.capture_performance, Some(json!(false)));
        assert!(response.config.autocapture_opt_out.is_none());
        assert!(response.config.capture_dead_clicks.is_none());
    }

    #[test]
    fn test_team_exclusion_all_teams() {
        let mut config = Config::default_test_config();
        config.new_analytics_capture_excluded_team_ids = TeamIdCollection::All; // All means exclude all teams
        config.element_chain_as_string_excluded_teams = TeamIdCollection::All; // All means exclude all teams

        let mut response = create_base_response();
        let team = create_base_team();

        apply_config_fields_test_only(&mut response, &config, &team);

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

        apply_config_fields_test_only(&mut response, &config, &team);

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

        apply_config_fields_test_only(&mut response, &config, &team);

        // Both should be enabled for team id 1 (not in exclusion list)
        assert!(response.config.analytics.is_some());
        assert_eq!(response.config.elements_chain_as_string, Some(true));
    }

    #[test]
    fn test_session_recording_disabled() {
        let config = Config::default_test_config();
        let mut team = create_base_team();
        team.session_recording_opt_in = false; // Disabled

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers, &config);

        // Should return disabled=false when session recording is off
        if let Some(SessionRecordingField::Disabled(enabled)) = result {
            assert!(!enabled);
        } else {
            panic!("Expected SessionRecordingField::Disabled(false)");
        }
    }

    #[test]
    fn test_session_recording_enabled_no_rrweb_script() {
        let config = Config::default_test_config();
        let mut team = create_base_team();
        team.session_recording_opt_in = true; // Enabled

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers, &config);

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
    fn test_session_recording_rrweb_script_wildcard_allowed() {
        let mut config = Config::default_test_config();
        config.session_replay_rrweb_script = "console.log('custom script')".to_string();
        config.session_replay_rrweb_script_allowed_teams = "all".parse().unwrap(); // All teams allowed

        let mut team = create_base_team();
        team.session_recording_opt_in = true;
        team.id = 123; // Any team ID should work with "all"

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers, &config);

        if let Some(SessionRecordingField::Config(config)) = result {
            assert!(config.script_config.is_some());
            let script_config = config.script_config.unwrap();
            assert_eq!(script_config["script"], "console.log('custom script')");
        } else {
            panic!("Expected SessionRecordingField::Config with script_config");
        }
    }

    #[test]
    fn test_session_recording_rrweb_script_specific_team_allowed() {
        let mut config = Config::default_test_config();
        config.session_replay_rrweb_script = "console.log('team script')".to_string();
        config.session_replay_rrweb_script_allowed_teams = "1,5,10".parse().unwrap(); // Team 1 is allowed

        let mut team = create_base_team();
        team.session_recording_opt_in = true;
        team.id = 1; // Team 1 is in the allowed list

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers, &config);

        if let Some(SessionRecordingField::Config(config)) = result {
            assert!(config.script_config.is_some());
            let script_config = config.script_config.unwrap();
            assert_eq!(script_config["script"], "console.log('team script')");
        } else {
            panic!("Expected SessionRecordingField::Config with script_config");
        }
    }

    #[test]
    fn test_session_recording_rrweb_script_team_not_allowed() {
        let mut config = Config::default_test_config();
        config.session_replay_rrweb_script = "console.log('restricted script')".to_string();
        config.session_replay_rrweb_script_allowed_teams = "5,10,15".parse().unwrap(); // Team 1 is NOT in list

        let mut team = create_base_team();
        team.session_recording_opt_in = true;
        team.id = 1; // Team 1 is not in the allowed list

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers, &config);

        if let Some(SessionRecordingField::Config(config)) = result {
            assert!(config.script_config.is_none()); // Should not have script config
        } else {
            panic!("Expected SessionRecordingField::Config without script_config");
        }
    }

    #[test]
    fn test_session_recording_rrweb_script_empty_string() {
        let mut config = Config::default_test_config();
        config.session_replay_rrweb_script = "".to_string(); // Empty script
        config.session_replay_rrweb_script_allowed_teams = "all".parse().unwrap();

        let mut team = create_base_team();
        team.session_recording_opt_in = true;

        let headers = axum::http::HeaderMap::new();
        let result = session_recording::session_recording_config_response(&team, &headers, &config);

        if let Some(SessionRecordingField::Config(config)) = result {
            assert!(config.script_config.is_none()); // Should not have script config when script is empty
        } else {
            panic!("Expected SessionRecordingField::Config without script_config");
        }
    }
}
