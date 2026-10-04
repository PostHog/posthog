//! Config sanitization for public-facing responses.
//!
//! Matches Python's `sanitize_config_for_public_cdn` behavior:
//! - Removes unused public config and survey fields
//! - Removes `siteAppsJS` (raw JS only needed for array.js bundle, not JSON API)
//! - Removes `sessionRecording.domains` (internal field, not needed by SDK)
//! - Sets `sessionRecording` to `false` if request origin not in permitted domains,
//!   and names the reason on the response

use axum::http::HeaderMap;
use common_metrics::inc;
use common_replay_domains::{sanitize_session_recording, set_session_recording_disabled_reason};
use serde_json::Value;

const SESSION_RECORDING_DISABLED_COUNTER: &str = "remote_config_session_recording_disabled_total";

/// Sanitize cached config before returning to clients.
pub fn sanitize_config_for_client(cached_config: &mut Value, headers: &HeaderMap) {
    if let Some(obj) = cached_config.as_object_mut() {
        obj.remove("siteAppsJS");
        obj.remove("token");
    }
    sanitize_surveys_for_client(cached_config);

    if let Some(reason) = sanitize_session_recording(cached_config, headers) {
        set_session_recording_disabled_reason(cached_config, reason);
        inc(
            SESSION_RECORDING_DISABLED_COUNTER,
            &[("reason".to_string(), reason.as_str().to_string())],
            1,
        );
    }
}

pub fn sanitize_surveys_for_client(payload: &mut Value) {
    let Some(payload) = payload.as_object_mut() else {
        return;
    };
    payload.remove("survey_config");

    let Some(surveys) = payload.get_mut("surveys").and_then(Value::as_array_mut) else {
        return;
    };

    for survey in surveys {
        let Some(survey) = survey.as_object_mut() else {
            continue;
        };
        survey.remove("base_language");

        if let Some(questions) = survey.get_mut("questions").and_then(Value::as_array_mut) {
            for question in questions {
                if let Some(question) = question.as_object_mut() {
                    question.remove("isNpsQuestion");
                }
            }
        }

        let Some(actions) = survey
            .get_mut("conditions")
            .and_then(Value::as_object_mut)
            .and_then(|conditions| conditions.get_mut("actions"))
            .and_then(Value::as_object_mut)
            .and_then(|actions| actions.get_mut("values"))
            .and_then(Value::as_array_mut)
        else {
            continue;
        };

        for action in actions {
            if let Some(action) = action.as_object_mut() {
                action.retain(|field, _| matches!(field.as_str(), "id" | "name" | "steps"));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_replay_domains::SESSION_RECORDING_DISABLED_REASON_KEY;
    use serde_json::json;

    #[test]
    fn test_removes_site_apps_js() {
        let mut config = json!({
            "token": "phc_test",
            "siteApps": [{"id": 1}],
            "siteAppsJS": ["function() {}"],
            "heatmaps": true
        });

        sanitize_config_for_client(&mut config, &HeaderMap::new());

        assert!(config.get("token").is_none());
        assert!(config.get("siteAppsJS").is_none());
        assert!(config.get("siteApps").is_some());
        assert_eq!(config.get("heatmaps"), Some(&json!(true)));
    }

    #[test]
    fn test_strips_session_recording_domains() {
        let mut config = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": ["https://example.com"]
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://example.com".parse().unwrap());

        sanitize_config_for_client(&mut config, &headers);

        let sr = config.get("sessionRecording").unwrap();
        assert!(sr.is_object());
        assert!(sr.get("domains").is_none());
        assert_eq!(sr.get("endpoint"), Some(&json!("/s/")));
        assert!(config.get(SESSION_RECORDING_DISABLED_REASON_KEY).is_none());
    }

    #[test]
    fn test_disables_recording_for_wrong_domain() {
        let mut config = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": ["https://allowed.com"]
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://evil.com".parse().unwrap());

        sanitize_config_for_client(&mut config, &headers);

        assert_eq!(config.get("sessionRecording"), Some(&json!(false)));
        assert_eq!(
            config.get(SESSION_RECORDING_DISABLED_REASON_KEY),
            Some(&json!("domain_not_allowed"))
        );
    }

    #[test]
    fn test_empty_domains_allows_all() {
        let mut config = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": []
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://any-site.com".parse().unwrap());

        sanitize_config_for_client(&mut config, &headers);

        let sr = config.get("sessionRecording").unwrap();
        assert!(sr.is_object());
    }

    #[test]
    fn test_no_session_recording_field_is_noop() {
        let mut config = json!({"heatmaps": true});

        sanitize_config_for_client(&mut config, &HeaderMap::new());

        assert_eq!(config, json!({"heatmaps": true}));
    }

    #[test]
    fn test_session_recording_false_passes_through() {
        let mut config = json!({"sessionRecording": false});

        sanitize_config_for_client(&mut config, &HeaderMap::new());

        assert_eq!(config.get("sessionRecording"), Some(&json!(false)));
        assert_eq!(
            config.get(SESSION_RECORDING_DISABLED_REASON_KEY),
            Some(&json!("not_enabled"))
        );
    }

    #[test]
    fn test_session_recording_false_over_quota_reports_the_quota() {
        let mut config = json!({
            "sessionRecording": false,
            "quotaLimited": ["recordings"]
        });

        sanitize_config_for_client(&mut config, &HeaderMap::new());

        assert_eq!(
            config.get(SESSION_RECORDING_DISABLED_REASON_KEY),
            Some(&json!("quota_limited"))
        );
    }
}
