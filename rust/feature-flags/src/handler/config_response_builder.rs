use crate::{
    api::{
        errors::FlagError,
        types::{ConfigResponse, FlagsResponse},
    },
    config_cache::get_cached_config,
    handler::session_recording::on_permitted_domain,
    metrics::consts::TOMBSTONE_COUNTER,
    team::team_models::Team,
};
use axum::http::HeaderMap;
use limiters::redis::QuotaResource;
use metrics::counter;
use serde_json::{json, Value};

use super::types::RequestContext;

/// Build response by passing through cached config from Python's HyperCache.
///
/// The config blob is passed through as-is without interpretation.
/// Session recording quota limiting is applied in Rust using real-time checks.
pub async fn build_response_from_cache(
    flags_response: FlagsResponse,
    context: &RequestContext,
    team: &Team,
) -> Result<FlagsResponse, FlagError> {
    let mut response = flags_response;

    if !context.meta.config.unwrap_or(false) {
        return Ok(response);
    }

    let is_recordings_limited = if context.state.config.flags_session_replay_quota_check {
        context
            .state
            .session_replay_billing_limiter
            .is_limited(&team.api_token)
            .await
    } else {
        false
    };

    let mut cached_config =
        match get_cached_config(&context.state.config_hypercache_reader, &team.api_token).await {
            Some(Value::Object(map)) => Value::Object(map),
            Some(_) => {
                // Cached value is not a JSON object - this should never happen
                // Python always writes config as a JSON object to hypercache
                tracing::warn!(
                    team_id = team.id,
                    api_token = %team.api_token,
                    "Config cache returned non-object value - returning fallback config"
                );
                counter!(
                    TOMBSTONE_COUNTER,
                    "namespace" => "feature_flags",
                    "operation" => "config_cache_non_object",
                    "component" => "config_response_builder",
                )
                .increment(1);

                return Ok(apply_fallback_config(response, team, is_recordings_limited));
            }
            None => {
                // Cache miss - return minimal fallback config with quota info
                tracing::warn!(
                    team_id = team.id,
                    api_token = %team.api_token,
                    "Config cache miss - returning fallback config"
                );

                return Ok(apply_fallback_config(response, team, is_recordings_limited));
            }
        };

    // Sanitize config for client consumption (removes internal fields, applies domain filtering)
    sanitize_config_for_client(&mut cached_config, &context.headers);

    if is_recordings_limited {
        cached_config["sessionRecording"] = json!(false);
    }

    response.config = ConfigResponse::from_value(cached_config);

    if is_recordings_limited {
        set_recordings_quota_limited(&mut response);
    } else {
        set_cached_quota_limits_without_recordings(&mut response);
    }

    tracing::debug!(
        team_id = team.id,
        "Passed through cached config from HyperCache"
    );

    Ok(response)
}

/// Apply fallback config when cache is unavailable or returns unexpected data.
fn apply_fallback_config(
    mut response: FlagsResponse,
    team: &Team,
    is_recordings_limited: bool,
) -> FlagsResponse {
    let has_flags = !response.flags.is_empty();
    response.config = ConfigResponse::fallback(&team.api_token, has_flags);

    if is_recordings_limited {
        response.quota_limited = Some(vec![QuotaResource::Recordings.as_str().to_string()]);
    }

    response
}

/// Set quota_limited to include "recordings" when recordings are quota limited.
/// Merges with any existing quota limits from the config.
fn set_recordings_quota_limited(response: &mut FlagsResponse) {
    let mut limited: Vec<String> = response
        .config
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

/// Set quota_limited from cached config, filtering out stale "recordings" entries.
/// Used when recordings are NOT quota limited (real-time check says no).
fn set_cached_quota_limits_without_recordings(response: &mut FlagsResponse) {
    let recordings_str = QuotaResource::Recordings.as_str();

    if let Some(arr) = response
        .config
        .get("quotaLimited")
        .and_then(|v| v.as_array())
    {
        let filtered: Vec<String> = arr
            .iter()
            .filter_map(|v| v.as_str())
            .filter(|&s| s != recordings_str)
            .map(String::from)
            .collect();

        if !filtered.is_empty() {
            response.quota_limited = Some(filtered);
        }
    }
}

/// Sanitize cached config before returning to clients.
///
/// Matches Python's `sanitize_config_for_public_cdn` behavior:
/// - Removes `siteAppsJS` (raw JS only needed for array.js bundle, not JSON API)
/// - Removes `sessionRecording.domains` (internal field, not needed by SDK)
/// - Sets `sessionRecording` to `false` if request origin not in permitted domains
fn sanitize_config_for_client(cached_config: &mut Value, headers: &HeaderMap) {
    if let Some(obj) = cached_config.as_object_mut() {
        obj.remove("siteAppsJS");
    }

    let session_recording = match cached_config.get_mut("sessionRecording") {
        Some(sr) => sr,
        None => return,
    };

    let obj = match session_recording.as_object_mut() {
        Some(o) => o,
        None => return,
    };

    let domains = obj.remove("domains");

    // Check domain permission if domains list exists and is non-empty
    if let Some(domains_value) = domains {
        if let Some(domains_array) = domains_value.as_array() {
            let domain_strings: Vec<String> = domains_array
                .iter()
                .filter_map(|d| d.as_str().map(String::from))
                .collect();

            // Empty domains list means always permitted
            if !domain_strings.is_empty() && !on_permitted_domain(&domain_strings, headers) {
                *session_recording = json!(false);
            }
        }
    }
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
    fn test_set_recordings_quota_limited_adds_to_empty() {
        let mut response = create_base_response();
        response.config = ConfigResponse::from_value(json!({}));

        set_recordings_quota_limited(&mut response);

        assert_eq!(response.quota_limited, Some(vec!["recordings".to_string()]));
    }

    #[test]
    fn test_set_recordings_quota_limited_merges_existing() {
        let mut response = create_base_response();
        response.config = ConfigResponse::from_value(json!({"quotaLimited": ["feature_flags"]}));

        set_recordings_quota_limited(&mut response);

        assert_eq!(
            response.quota_limited,
            Some(vec!["feature_flags".to_string(), "recordings".to_string()])
        );
    }

    #[test]
    fn test_set_recordings_quota_limited_no_duplicate() {
        let mut response = create_base_response();
        response.config = ConfigResponse::from_value(json!({"quotaLimited": ["recordings"]}));

        set_recordings_quota_limited(&mut response);

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

    #[test]
    fn test_cached_quota_limits_filters_stale_recordings() {
        let mut response = create_base_response();
        // Cached config has stale "recordings" limit
        response.config =
            ConfigResponse::from_value(json!({"quotaLimited": ["recordings", "feature_flags"]}));

        set_cached_quota_limits_without_recordings(&mut response);

        // "recordings" should be filtered out, only "feature_flags" remains
        assert_eq!(
            response.quota_limited,
            Some(vec!["feature_flags".to_string()])
        );
    }

    #[test]
    fn test_cached_quota_limits_filters_only_recordings() {
        let mut response = create_base_response();
        // Cached config has only stale "recordings" limit
        response.config = ConfigResponse::from_value(json!({"quotaLimited": ["recordings"]}));

        set_cached_quota_limits_without_recordings(&mut response);

        // Should be None since filtering "recordings" leaves empty list
        assert_eq!(response.quota_limited, None);
    }

    #[test]
    fn test_cached_quota_limits_preserves_other_limits() {
        let mut response = create_base_response();
        // Cached config has no "recordings" limit
        response.config =
            ConfigResponse::from_value(json!({"quotaLimited": ["feature_flags", "events"]}));

        set_cached_quota_limits_without_recordings(&mut response);

        assert_eq!(
            response.quota_limited,
            Some(vec!["feature_flags".to_string(), "events".to_string()])
        );
    }

    #[test]
    fn test_cached_quota_limits_handles_empty() {
        let mut response = create_base_response();
        response.config = ConfigResponse::from_value(json!({}));

        set_cached_quota_limits_without_recordings(&mut response);

        assert_eq!(response.quota_limited, None);
    }

    #[test]
    fn test_sanitize_removes_site_apps_js() {
        // siteAppsJS contains raw transpiled JavaScript, only needed for array.js bundle
        let mut cached = json!({
            "siteApps": [{"id": 1, "url": "https://example.com/app.js"}],
            "siteAppsJS": "function() { console.log('raw js'); }",
            "heatmaps": true
        });

        sanitize_config_for_client(&mut cached, &HeaderMap::new());

        assert!(
            cached.get("siteAppsJS").is_none(),
            "siteAppsJS must be removed"
        );
        assert!(
            cached.get("siteApps").is_some(),
            "siteApps should be preserved"
        );
        assert_eq!(cached.get("heatmaps"), Some(&json!(true)));
    }

    #[test]
    fn test_session_recording_empty_domains_allowed() {
        // Empty domains list means "allow all" - recording should remain enabled
        let mut cached = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": []
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://any.site.com".parse().unwrap());

        sanitize_config_for_client(&mut cached, &headers);

        let sr = cached.get("sessionRecording").unwrap();
        assert!(sr.is_object(), "sessionRecording should remain as config");
        assert!(sr.get("domains").is_none(), "domains must be stripped");
    }

    #[test]
    fn test_session_recording_no_domains_field_allowed() {
        // No domains field means "allow all" - recording should remain enabled
        // Note: Python always includes domains field, so this is defensive
        let mut cached = json!({
            "sessionRecording": {
                "endpoint": "/s/"
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://any.site.com".parse().unwrap());

        sanitize_config_for_client(&mut cached, &headers);

        let sr = cached.get("sessionRecording").unwrap();
        assert!(sr.is_object());
    }

    #[test]
    fn test_session_recording_domain_not_permitted_disables_recording() {
        // Request from non-permitted domain should disable recording entirely
        let mut cached = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": ["https://allowed.example.com"]
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://evil.site.com".parse().unwrap());

        sanitize_config_for_client(&mut cached, &headers);

        assert_eq!(
            cached.get("sessionRecording"),
            Some(&json!(false)),
            "sessionRecording must be false when domain not permitted"
        );
    }

    #[test]
    fn test_session_recording_domain_permitted_preserves_config() {
        // Request from permitted domain should preserve config and strip domains
        let mut cached = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "consoleLogRecordingEnabled": true,
                "domains": ["https://allowed.example.com"]
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://allowed.example.com".parse().unwrap());

        sanitize_config_for_client(&mut cached, &headers);

        let sr = cached.get("sessionRecording").unwrap();
        assert!(sr.is_object());
        assert_eq!(sr.get("endpoint"), Some(&json!("/s/")));
        assert_eq!(sr.get("consoleLogRecordingEnabled"), Some(&json!(true)));
        assert!(sr.get("domains").is_none(), "domains must be stripped");
    }

    #[test]
    fn test_session_recording_already_false_unchanged() {
        // sessionRecording=false (e.g., opt-out) should pass through unchanged
        let mut cached = json!({
            "sessionRecording": false
        });

        sanitize_config_for_client(&mut cached, &HeaderMap::new());

        assert_eq!(cached.get("sessionRecording"), Some(&json!(false)));
    }
}
