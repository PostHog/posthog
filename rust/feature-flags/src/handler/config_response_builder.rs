use crate::{
    api::{
        errors::FlagError,
        types::{ConfigResponse, FlagsResponse},
    },
    config_cache::get_cached_config,
    handler::session_recording::on_permitted_domain,
    team::team_models::Team,
};
use axum::http::HeaderMap;
use limiters::redis::QuotaResource;
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
            Some(config) => config,
            None => {
                // Cache miss - return minimal fallback config with quota info
                tracing::warn!(
                    team_id = team.id,
                    api_token = %team.api_token,
                    "Config cache miss - returning fallback config"
                );

                let has_flags = !response.flags.is_empty();
                response.config = ConfigResponse::fallback(&team.api_token, has_flags);

                if is_recordings_limited {
                    response.quota_limited =
                        Some(vec![QuotaResource::Recordings.as_str().to_string()]);
                }

                return Ok(response);
            }
        };

    // Apply session recording domain filtering
    apply_session_recording_domain_filter(&mut cached_config, &context.headers);

    // Real-time quota check takes precedence over cached values.
    if is_recordings_limited {
        apply_recordings_quota_limit(&mut response, &cached_config);
    } else {
        apply_cached_quota_limits_without_recordings(&mut response, &cached_config);
    }

    response.config = ConfigResponse::from_value(cached_config);

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

/// Apply cached quota limits, filtering out "recordings".
fn apply_cached_quota_limits_without_recordings(
    response: &mut FlagsResponse,
    cached_config: &Value,
) {
    let recordings_str = QuotaResource::Recordings.as_str();

    if let Some(arr) = cached_config.get("quotaLimited").and_then(|v| v.as_array()) {
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

/// Apply session recording domain filtering to the cached config.
///
/// This removes `domains` from sessionRecording and sets sessionRecording=false
/// if the request origin is not in the permitted domains list.
fn apply_session_recording_domain_filter(cached_config: &mut Value, headers: &HeaderMap) {
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

    #[test]
    fn test_cached_quota_limits_filters_stale_recordings() {
        let mut response = create_base_response();
        // Cached config has stale "recordings" limit
        let cached = json!({"quotaLimited": ["recordings", "feature_flags"]});

        apply_cached_quota_limits_without_recordings(&mut response, &cached);

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
        let cached = json!({"quotaLimited": ["recordings"]});

        apply_cached_quota_limits_without_recordings(&mut response, &cached);

        // Should be None since filtering "recordings" leaves empty list
        assert_eq!(response.quota_limited, None);
    }

    #[test]
    fn test_cached_quota_limits_preserves_other_limits() {
        let mut response = create_base_response();
        // Cached config has no "recordings" limit
        let cached = json!({"quotaLimited": ["feature_flags", "events"]});

        apply_cached_quota_limits_without_recordings(&mut response, &cached);

        assert_eq!(
            response.quota_limited,
            Some(vec!["feature_flags".to_string(), "events".to_string()])
        );
    }

    #[test]
    fn test_cached_quota_limits_handles_empty() {
        let mut response = create_base_response();
        let cached = json!({});

        apply_cached_quota_limits_without_recordings(&mut response, &cached);

        assert_eq!(response.quota_limited, None);
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

        apply_session_recording_domain_filter(&mut cached, &headers);

        let sr = cached.get("sessionRecording").unwrap();
        assert!(sr.is_object(), "sessionRecording should remain as config");
        assert!(sr.get("domains").is_none(), "domains must be stripped");
    }

    #[test]
    fn test_session_recording_no_domains_field_allowed() {
        // No domains field means "allow all" - recording should remain enabled
        let mut cached = json!({
            "sessionRecording": {
                "endpoint": "/s/"
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://any.site.com".parse().unwrap());

        apply_session_recording_domain_filter(&mut cached, &headers);

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

        apply_session_recording_domain_filter(&mut cached, &headers);

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

        apply_session_recording_domain_filter(&mut cached, &headers);

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

        apply_session_recording_domain_filter(&mut cached, &HeaderMap::new());

        assert_eq!(cached.get("sessionRecording"), Some(&json!(false)));
    }
}
