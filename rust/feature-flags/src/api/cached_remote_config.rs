//! Cached remote config from Python's RemoteConfig.build_config()
//!
//! This module defines the structure for deserializing the pre-computed config
//! blob stored in HyperCache by Python's RemoteConfig.sync() method.
//!
//! The config is stored at cache key: `cache/team_tokens/{api_token}/array/config.json`

use crate::api::types::{
    AnalyticsConfig, ConfigResponse, ErrorTrackingConfig, LogsConfig, SessionRecordingConfig,
    SessionRecordingField,
};
use crate::site_apps::WebJsUrl;
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Cached remote config from Python's RemoteConfig.build_config()
#[derive(Debug, Clone, Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CachedRemoteConfig {
    /// Team API token
    pub token: Option<String>,

    /// Supported compression algorithms (e.g., ["gzip", "gzip-js"])
    pub supported_compression: Option<Vec<String>>,

    /// Whether the team has active feature flags
    pub has_feature_flags: Option<bool>,

    /// Whether to capture dead clicks
    pub capture_dead_clicks: Option<bool>,

    /// Capture performance config - can be `false` or an object with network_timing, web_vitals
    pub capture_performance: Option<Value>,

    /// If set, disables autocapture (note: uses snake_case in Python output)
    #[serde(rename = "autocapture_opt_out")]
    pub autocapture_opt_out: Option<bool>,

    /// Autocapture exceptions setting - Python sends boolean
    pub autocapture_exceptions: Option<bool>,

    /// Analytics endpoint config
    pub analytics: Option<CachedAnalyticsConfig>,

    /// Whether elements chain should be sent as string
    pub elements_chain_as_string: Option<bool>,

    /// Error tracking configuration
    pub error_tracking: Option<CachedErrorTrackingConfig>,

    /// Logs configuration
    pub logs: Option<CachedLogsConfig>,

    /// Session recording config - can be `false` or full config object
    pub session_recording: Option<Value>,

    /// Whether heatmaps are enabled
    pub heatmaps: Option<bool>,

    /// Conversations widget config - can be `false` or config object
    pub conversations: Option<Value>,

    /// Surveys config - can be `false` or array of surveys
    pub surveys: Option<Value>,

    /// Survey configuration
    pub survey_config: Option<Value>,

    /// Product tours - can be `false` or `true`
    pub product_tours: Option<Value>,

    /// Whether to only capture identified users by default
    pub default_identified_only: Option<bool>,

    /// Site apps configuration
    pub site_apps: Option<Vec<CachedSiteApp>>,

    /// Site apps JavaScript (internal use only, not exposed to client)
    #[serde(rename = "siteAppsJS")]
    pub site_apps_js: Option<Vec<String>>,

    /// Quota limited resources (e.g., ["recordings"])
    pub quota_limited: Option<Vec<String>>,

    /// Flags persistence default
    pub flags_persistence_default: Option<bool>,
}

/// Cached analytics config from Python
#[derive(Debug, Clone, Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CachedAnalyticsConfig {
    pub endpoint: Option<String>,
}

/// Cached error tracking config from Python
#[derive(Debug, Clone, Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CachedErrorTrackingConfig {
    pub autocapture_exceptions: Option<bool>,
    pub suppression_rules: Option<Vec<Value>>,
}

/// Cached logs config from Python
#[derive(Debug, Clone, Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CachedLogsConfig {
    pub capture_console_logs: Option<bool>,
}

/// Cached site app config from Python
#[derive(Debug, Clone, Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CachedSiteApp {
    pub id: Option<i64>,
    pub url: Option<String>,
}

/// Session recording config from Python (when not disabled)
#[derive(Debug, Clone, Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CachedSessionRecordingConfig {
    pub endpoint: Option<String>,
    pub console_log_recording_enabled: Option<bool>,
    pub recorder_version: Option<String>,
    pub sample_rate: Option<Value>,
    pub minimum_duration_milliseconds: Option<Value>,
    pub linked_flag: Option<Value>,
    pub network_payload_capture: Option<Value>,
    pub masking: Option<Value>,
    pub url_triggers: Option<Vec<Value>>,
    pub url_blocklist: Option<Vec<Value>>,
    pub event_triggers: Option<Vec<Value>>,
    pub trigger_match_type: Option<String>,
    pub script_config: Option<Value>,
    /// Domains - internal use, sanitized before client response
    pub domains: Option<Vec<String>>,
}

impl From<CachedRemoteConfig> for ConfigResponse {
    fn from(cached: CachedRemoteConfig) -> Self {
        ConfigResponse {
            supported_compression: cached
                .supported_compression
                .unwrap_or_else(|| vec!["gzip".to_string(), "gzip-js".to_string()]),
            autocapture_opt_out: cached.autocapture_opt_out,
            capture_performance: cached.capture_performance,
            config: Some(serde_json::json!({"enable_collect_everything": true})),
            analytics: cached.analytics.map(|a| AnalyticsConfig {
                endpoint: a.endpoint,
            }),
            elements_chain_as_string: cached.elements_chain_as_string,
            autocapture_exceptions: Some(match cached.autocapture_exceptions {
                Some(true) => serde_json::json!({"endpoint": "/e/"}),
                _ => serde_json::json!(false),
            }),
            session_recording: map_session_recording(cached.session_recording),
            surveys: cached.surveys,
            logs: cached.logs.map(|l| LogsConfig {
                capture_console_logs: l.capture_console_logs,
            }),
            toolbar_params: Some(serde_json::json!({})),
            is_authenticated: Some(false),
            site_apps: cached.site_apps.map(|apps| {
                apps.into_iter()
                    .filter_map(|a| {
                        Some(WebJsUrl::new(a.id? as i32, a.url?, "site_app".to_string()))
                    })
                    .collect()
            }),
            heatmaps: cached.heatmaps,
            flags_persistence_default: cached.flags_persistence_default,
            default_identified_only: cached.default_identified_only,
            capture_dead_clicks: cached.capture_dead_clicks,
            error_tracking: cached.error_tracking.map(|et| ErrorTrackingConfig {
                autocapture_exceptions: et.autocapture_exceptions.unwrap_or(false),
                suppression_rules: et.suppression_rules.unwrap_or_default(),
            }),
            conversations: cached.conversations,
        }
    }
}

/// Map session recording config from Python's Value to Rust's SessionRecordingField.
///
/// Python sends either:
/// - `false` - session recording disabled
/// - Object with recording config - session recording enabled
fn map_session_recording(config: Option<Value>) -> Option<SessionRecordingField> {
    match config {
        None => Some(SessionRecordingField::Disabled(false)),
        Some(Value::Bool(false)) => Some(SessionRecordingField::Disabled(false)),
        Some(Value::Object(mut obj)) => {
            // Remove domains field - SDK handles domain filtering
            obj.remove("domains");
            let config_value = Value::Object(obj);

            // Try to parse as SessionRecordingConfig
            match serde_json::from_value::<SessionRecordingConfig>(config_value) {
                Ok(config) => Some(SessionRecordingField::Config(Box::new(config))),
                Err(e) => {
                    tracing::warn!(
                        error = %e,
                        "Failed to parse cached session recording config, disabling"
                    );
                    Some(SessionRecordingField::Disabled(false))
                }
            }
        }
        _ => Some(SessionRecordingField::Disabled(false)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_deserialize_minimal_config() {
        let json = r#"{
            "supportedCompression": ["gzip", "gzip-js"],
            "defaultIdentifiedOnly": true
        }"#;

        let config: CachedRemoteConfig = serde_json::from_str(json).unwrap();
        assert_eq!(
            config.supported_compression,
            Some(vec!["gzip".to_string(), "gzip-js".to_string()])
        );
        assert_eq!(config.default_identified_only, Some(true));
    }

    #[test]
    fn test_deserialize_full_config() {
        let json = r#"{
            "token": "phc_12345",
            "supportedCompression": ["gzip", "gzip-js"],
            "hasFeatureFlags": false,
            "captureDeadClicks": false,
            "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null},
            "autocapture_opt_out": false,
            "autocaptureExceptions": false,
            "analytics": {"endpoint": "/i/v0/e/"},
            "elementsChainAsString": true,
            "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []},
            "logs": {"captureConsoleLogs": false},
            "sessionRecording": false,
            "heatmaps": false,
            "conversations": false,
            "surveys": false,
            "productTours": false,
            "defaultIdentifiedOnly": true,
            "siteApps": []
        }"#;

        let config: CachedRemoteConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.token, Some("phc_12345".to_string()));
        assert_eq!(config.has_feature_flags, Some(false));
        assert_eq!(config.autocapture_opt_out, Some(false));
        assert_eq!(config.elements_chain_as_string, Some(true));
    }

    #[test]
    fn test_deserialize_session_recording_disabled() {
        let json = r#"{"sessionRecording": false}"#;
        let config: CachedRemoteConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.session_recording, Some(serde_json::json!(false)));
    }

    #[test]
    fn test_deserialize_session_recording_enabled() {
        let json = r#"{
            "sessionRecording": {
                "endpoint": "/s/",
                "consoleLogRecordingEnabled": true,
                "recorderVersion": "v2",
                "sampleRate": null,
                "minimumDurationMilliseconds": null
            }
        }"#;
        let config: CachedRemoteConfig = serde_json::from_str(json).unwrap();
        assert!(config.session_recording.is_some());
        let sr = config.session_recording.unwrap();
        assert!(sr.is_object());
    }

    #[test]
    fn test_deserialize_error_tracking() {
        let json = r#"{
            "errorTracking": {
                "autocaptureExceptions": true,
                "suppressionRules": [{"type": "error", "value": "test"}]
            }
        }"#;
        let config: CachedRemoteConfig = serde_json::from_str(json).unwrap();
        let et = config.error_tracking.unwrap();
        assert_eq!(et.autocapture_exceptions, Some(true));
        assert!(et.suppression_rules.is_some());
    }
}
