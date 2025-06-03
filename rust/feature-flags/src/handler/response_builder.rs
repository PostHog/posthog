use crate::{
    api::{
        errors::FlagError,
        types::{AnalyticsConfig, FlagsResponse},
    },
    site_apps::get_decide_site_apps,
    team::team_models::Team,
};
use std::collections::HashMap;

use super::{session_recording, types::RequestContext};

pub async fn build_response(
    flags_response: FlagsResponse,
    context: &RequestContext,
    team: &Team,
) -> Result<FlagsResponse, FlagError> {
    // Start with the flags response that already has core data populated
    let mut response = flags_response;

    // Only add config fields if explicitly requested
    if context.meta.config.unwrap_or(false) {
        apply_config_fields(&mut response, context, team).await?;
    }

    Ok(response)
}

async fn apply_config_fields(
    response: &mut FlagsResponse,
    context: &RequestContext,
    team: &Team,
) -> Result<(), FlagError> {
    let capture_web_vitals = team.autocapture_web_vitals_opt_in.unwrap_or(false);
    let autocapture_web_vitals_allowed_metrics =
        team.autocapture_web_vitals_allowed_metrics.as_ref();
    let capture_network_timing = team.capture_performance_opt_in.unwrap_or(false);

    response.has_feature_flags = Some(!response.flags.is_empty());
    response.supported_compression = vec!["gzip".to_string(), "gzip-js".to_string()];
    response.autocapture_opt_out = team.autocapture_opt_out;

    response.analytics = if !context.state.config.debug
        && !context.state.config.is_team_excluded(
            team.id,
            &context.state.config.new_analytics_capture_excluded_team_ids,
        ) {
        Some(AnalyticsConfig {
            endpoint: Some(context.state.config.new_analytics_capture_endpoint.clone()),
        })
    } else {
        None
    };

    response.elements_chain_as_string = if !context.state.config.is_team_excluded(
        team.id,
        &context.state.config.element_chain_as_string_excluded_teams,
    ) {
        Some(true)
    } else {
        None
    };

    response.capture_performance = match (capture_network_timing, capture_web_vitals) {
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

    response.config = Some(serde_json::json!({"enable_collect_everything": true}));

    response.autocapture_exceptions = if team.autocapture_exceptions_opt_in.unwrap_or(false) {
        Some(serde_json::json!(HashMap::from([(
            "endpoint".to_string(),
            serde_json::json!("/e/")
        )])))
    } else {
        Some(serde_json::json!(false))
    };

    response.surveys = Some(serde_json::json!(team.surveys_opt_in.unwrap_or(false)));
    response.heatmaps = Some(team.heatmaps_opt_in.unwrap_or(false));
    response.default_identified_only = Some(true);
    response.flags_persistence_default = Some(team.flags_persistence_default.unwrap_or(false));
    response.session_recording =
        session_recording::session_recording_config_response(team, context);
    response.toolbar_params = serde_json::json!(HashMap::<String, serde_json::Value>::new());
    response.is_authenticated = Some(false);
    response.capture_dead_clicks = team.capture_dead_clicks;

    response.site_apps = if team.inject_web_apps.unwrap_or(false) {
        get_decide_site_apps(context.state.reader.clone(), team.id).await?
    } else {
        vec![]
    };

    Ok(())
}
