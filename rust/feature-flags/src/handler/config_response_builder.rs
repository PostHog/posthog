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

    let cached_config =
        match get_cached_config(&context.state.config_hypercache_reader, &team.api_token).await {
            Some(config) => config,
            None => {
                // Cache miss - Python hasn't populated the cache yet.
                // Return minimal fallback config
                tracing::warn!(
                    team_id = team.id,
                    api_token = %team.api_token,
                    "Config cache miss - returning fallback config"
                );

                let has_flags = !response.flags.is_empty();
                response.config = ConfigResponse::fallback(&team.api_token, has_flags);
                return Ok(response);
            }
        };

    response.config = ConfigResponse::from_value(cached_config.clone());

    let is_recordings_limited = if context.state.config.flags_session_replay_quota_check {
        context
            .state
            .session_replay_billing_limiter
            .is_limited(&team.api_token)
            .await
    } else {
        false
    };

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
    use uuid::Uuid;

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
    fn test_config_passthrough_preserves_all_fields() {
        let cached = json!({
            "supportedCompression": ["gzip", "gzip-js"],
            "heatmaps": true,
            "someNewField": "that rust doesn't know about",
            "nested": {"deeply": {"value": 123}}
        });

        let config = ConfigResponse::from_value(cached);

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
