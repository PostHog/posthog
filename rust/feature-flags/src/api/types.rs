use crate::flags::flag_matching::FeatureFlagMatch;
use crate::flags::flag_models::FeatureFlag;
use crate::{flags::flag_match_reason::FeatureFlagMatchReason, site_apps::WebJsUrl};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use uuid::Uuid;

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum FlagsResponseCode {
    Ok = 1,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum FlagValue {
    Boolean(bool),
    String(String),
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct LinkedFlag {
    pub flag: String,
    pub variant: String,
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SiteApp {
    pub id: f64,
    pub url: String,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Compression {
    #[serde(rename = "gzip", alias = "gzip-js")]
    Gzip,
    #[serde(rename = "base64")]
    Base64,
    #[default]
    #[serde(other)]
    Unsupported,
}

impl Compression {
    pub fn as_str(&self) -> &'static str {
        match self {
            Compression::Gzip => "gzip",
            Compression::Base64 => "base64",
            Compression::Unsupported => "unsupported",
        }
    }
}

#[derive(Clone, Deserialize, Default)]
pub struct FlagsQueryParams {
    /// Optional API version identifier, defaults to None (which returns a legacy response)
    #[serde(alias = "v")]
    pub version: Option<String>,

    /// Compression type for the incoming request
    pub compression: Option<Compression>,

    /// Library version (alias: "ver")
    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    /// Optional timestamp indicating when the request was sent
    #[serde(alias = "_")]
    pub sent_at: Option<i64>,

    #[serde(default)]
    pub config: Option<bool>,
}

#[derive(Debug, Serialize, Deserialize, Default, Clone)]
#[serde(rename_all = "camelCase")]
pub struct FlagsResponse {
    // Core flag data - always present
    pub errors_while_computing_flags: bool,
    pub flags: HashMap<String, FlagDetails>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
    pub request_id: Option<Uuid>,

    // Legacy format fields - always present when we have flags
    pub feature_flags: HashMap<String, FlagValue>,
    pub feature_flag_payloads: HashMap<String, Value>,

    // Config fields - only present when config=true
    #[serde(skip_serializing_if = "Vec::is_empty", default)]
    pub supported_compression: Vec<String>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub autocapture_opt_out: Option<bool>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub capture_performance: Option<Value>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub config: Option<Value>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub analytics: Option<AnalyticsConfig>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub elements_chain_as_string: Option<bool>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub autocapture_exceptions: Option<Value>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_recording: Option<SessionRecordingField>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub surveys: Option<Value>,

    #[serde(skip_serializing_if = "is_empty_value", default)]
    pub toolbar_params: Value,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_authenticated: Option<bool>,

    #[serde(skip_serializing_if = "Vec::is_empty", default)]
    pub site_apps: Vec<WebJsUrl>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub heatmaps: Option<bool>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub flags_persistence_default: Option<bool>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_identified_only: Option<bool>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub capture_dead_clicks: Option<bool>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub has_feature_flags: Option<bool>,
}

impl FlagsResponse {
    /// Create a new FlagsResponse with just the core flag data
    pub fn new(
        errors_while_computing_flags: bool,
        flags: HashMap<String, FlagDetails>,
        quota_limited: Option<Vec<String>>,
        request_id: Option<Uuid>,
    ) -> Self {
        let feature_flags = flags
            .iter()
            .map(|(k, v)| (k.clone(), v.to_value()))
            .collect();

        let feature_flag_payloads = flags
            .iter()
            .filter_map(|(k, v)| v.metadata.payload.clone().map(|p| (k.clone(), p)))
            .collect();

        Self {
            errors_while_computing_flags,
            flags,
            quota_limited,
            request_id,
            feature_flags,
            feature_flag_payloads,
            ..Default::default()
        }
    }

    /// Convert to legacy response format (for backward compatibility)
    pub fn to_legacy(&self) -> LegacyFlagsResponse {
        LegacyFlagsResponse {
            errors_while_computing_flags: self.errors_while_computing_flags,
            feature_flags: self.feature_flags.clone(),
            feature_flag_payloads: self.feature_flag_payloads.clone(),
            quota_limited: self.quota_limited.clone(),
            request_id: self.request_id.unwrap_or_else(Uuid::nil),
        }
    }

    /// Convert to a core flags response (strips config fields) - for API versioning
    pub fn to_flags_response(&self) -> FlagsResponse {
        FlagsResponse {
            errors_while_computing_flags: self.errors_while_computing_flags,
            flags: self.flags.clone(),
            quota_limited: self.quota_limited.clone(),
            request_id: self.request_id,
            feature_flags: self.feature_flags.clone(),
            feature_flag_payloads: self.feature_flag_payloads.clone(),
            // All config fields default to None/empty
            ..Default::default()
        }
    }
}

// Keep ServiceResponse for API versioning if needed
#[derive(Debug, Deserialize, Serialize)]
#[serde(untagged)]
pub enum ServiceResponse {
    Default(LegacyFlagsResponse),
    V2(FlagsResponse),
}

fn is_empty_value(val: &serde_json::Value) -> bool {
    match val {
        serde_json::Value::Object(map) => map.is_empty(),
        serde_json::Value::Array(arr) => arr.is_empty(),
        _ => false,
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct AnalyticsConfig {
    pub endpoint: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SessionRecordingConfig {
    pub endpoint: Option<String>,
    pub console_log_recording_enabled: Option<bool>,
    pub recorder_version: Option<String>,
    pub sample_rate: Option<String>,
    pub minimum_duration_milliseconds: Option<i32>,
    pub linked_flag: Option<Value>, // string or object
    pub network_payload_capture: Option<Value>,
    pub masking: Option<Value>,
    pub url_triggers: Option<Value>,
    pub script_config: Option<Value>,
    pub url_blocklist: Option<Value>,
    pub event_triggers: Option<Value>,
    pub trigger_match_type: Option<Value>,
    pub record_canvas: Option<bool>,
    pub canvas_fps: Option<u8>,
    pub canvas_quality: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum SessionRecordingField {
    Disabled(bool), // NB: this should only ever be false
    Config(SessionRecordingConfig),
}

impl Default for SessionRecordingField {
    fn default() -> Self {
        SessionRecordingField::Disabled(false)
    }
}

#[derive(Debug, PartialEq, Serialize, Deserialize, Default, Clone)]
#[serde(rename_all = "camelCase")]
pub struct LegacyFlagsResponse {
    pub errors_while_computing_flags: bool,
    pub feature_flags: HashMap<String, FlagValue>,
    pub feature_flag_payloads: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
    pub request_id: Uuid,
}

impl LegacyFlagsResponse {
    /// Create from any FlagsResponse - maintains backward compatibility
    pub fn from_response(response: FlagsResponse) -> Self {
        Self {
            errors_while_computing_flags: response.errors_while_computing_flags,
            feature_flags: response
                .flags
                .iter()
                .map(|(key, flag)| (key.clone(), flag.to_value()))
                .collect(),
            feature_flag_payloads: response
                .flags
                .iter()
                .filter_map(|(key, flag)| {
                    flag.metadata
                        .payload
                        .clone()
                        .map(|payload| (key.clone(), payload))
                })
                .collect(),
            quota_limited: response.quota_limited.clone(),
            request_id: response.request_id.unwrap_or_else(Uuid::nil),
        }
    }
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagsOptionsResponse {
    pub status: FlagsResponseCode,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagDetails {
    pub key: String,
    pub enabled: bool,
    pub variant: Option<String>,
    pub reason: FlagEvaluationReason,
    pub metadata: FlagDetailsMetadata,
}

impl FlagDetails {
    pub fn to_value(&self) -> FlagValue {
        if let Some(variant) = &self.variant {
            FlagValue::String(variant.clone())
        } else {
            FlagValue::Boolean(self.enabled)
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagDetailsMetadata {
    pub id: i32,
    pub version: i32,
    pub description: Option<String>,
    pub payload: Option<Value>,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagEvaluationReason {
    pub code: String,
    pub condition_index: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

pub trait FromFeatureAndMatch {
    fn create(flag: &FeatureFlag, flag_match: &FeatureFlagMatch) -> Self;
    fn create_error(flag: &FeatureFlag, error_reason: &str) -> Self;
    fn get_reason_description(match_info: &FeatureFlagMatch) -> Option<String>;
}

impl FromFeatureAndMatch for FlagDetails {
    fn create(flag: &FeatureFlag, flag_match: &FeatureFlagMatch) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: flag_match.matches,
            variant: flag_match.variant.clone(),
            reason: FlagEvaluationReason {
                code: flag_match.reason.to_string(),
                condition_index: flag_match.condition_index.map(|i| i as i32),
                description: Self::get_reason_description(flag_match),
            },
            metadata: FlagDetailsMetadata {
                id: flag.id,
                version: flag.version.unwrap_or(0),
                description: None,
                payload: flag_match.payload.clone(),
            },
        }
    }

    fn create_error(flag: &FeatureFlag, error_reason: &str) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: false,
            variant: None,
            reason: FlagEvaluationReason {
                code: error_reason.to_string(),
                condition_index: None,
                description: None,
            },
            metadata: FlagDetailsMetadata {
                id: flag.id,
                version: flag.version.unwrap_or(0),
                description: None,
                payload: None,
            },
        }
    }

    fn get_reason_description(match_info: &FeatureFlagMatch) -> Option<String> {
        match match_info.reason {
            FeatureFlagMatchReason::ConditionMatch => {
                let set_number = match_info.condition_index.unwrap_or(0) + 1;
                Some(format!("Matched condition set {}", set_number))
            }
            FeatureFlagMatchReason::NoConditionMatch => {
                Some("No matching condition set".to_string())
            }
            FeatureFlagMatchReason::OutOfRolloutBound => Some("Out of rollout bound".to_string()),
            FeatureFlagMatchReason::NoGroupType => Some("No group type".to_string()),
            FeatureFlagMatchReason::SuperConditionValue => {
                Some("Super condition value".to_string())
            }
            FeatureFlagMatchReason::HoldoutConditionValue => {
                Some("Holdout condition value".to_string())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_match_reason::FeatureFlagMatchReason;
    use crate::flags::flag_matching::FeatureFlagMatch;
    use rstest::rstest;
    use serde_json::json;

    #[rstest]
    #[case::condition_match(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::ConditionMatch,
            condition_index: Some(0),
            payload: None,
        },
        Some("Matched condition set 1".to_string())
    )]
    #[case::condition_match_different_set(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::ConditionMatch,
            condition_index: Some(2),
            payload: None,
        },
        Some("Matched condition set 3".to_string())
    )]
    #[case::no_condition_match(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::NoConditionMatch,
            condition_index: None,
            payload: None,
        },
        Some("No matching condition set".to_string())
    )]
    #[case::out_of_rollout(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::OutOfRolloutBound,
            condition_index: Some(2),
            payload: None,
        },
        Some("Out of rollout bound".to_string())
    )]
    #[case::no_group_type(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::NoGroupType,
            condition_index: None,
            payload: None,
        },
        Some("No group type".to_string())
    )]
    #[case::super_condition(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::SuperConditionValue,
            condition_index: None,
            payload: None,
        },
        Some("Super condition value".to_string())
    )]
    #[case::holdout_condition(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::HoldoutConditionValue,
            condition_index: None,
            payload: None,
        },
        Some("Holdout condition value".to_string())
    )]
    fn test_get_reason_description(
        #[case] flag_match: FeatureFlagMatch,
        #[case] expected_description: Option<String>,
    ) {
        assert_eq!(
            FlagDetails::get_reason_description(&flag_match),
            expected_description
        );
    }

    #[test]
    fn test_flags_response_only_includes_non_null_payloads() {
        // Create a response with multiple flags, some with payloads and some without
        let mut flags = HashMap::new();

        // Flag with payload
        flags.insert(
            "flag_with_payload".to_string(),
            FlagDetails {
                key: "flag_with_payload".to_string(),
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
                    payload: Some(json!({"key": "value"})),
                },
            },
        );

        // Flag without payload
        flags.insert(
            "flag2".to_string(),
            FlagDetails {
                key: "flag2".to_string(),
                enabled: true,
                variant: None,
                reason: FlagEvaluationReason {
                    code: "condition_match".to_string(),
                    condition_index: Some(0),
                    description: None,
                },
                metadata: FlagDetailsMetadata {
                    id: 2,
                    version: 1,
                    description: None,
                    payload: None,
                },
            },
        );

        // Flag with null payload, which should not be filtered out; since Some(Value::Null) is not None
        flags.insert(
            "flag_with_null_payload".to_string(),
            FlagDetails {
                key: "flag_with_null_payload".to_string(),
                enabled: true,
                variant: None,
                reason: FlagEvaluationReason {
                    code: "condition_match".to_string(),
                    condition_index: Some(0),
                    description: None,
                },
                metadata: FlagDetailsMetadata {
                    id: 3,
                    version: 1,
                    description: None,
                    payload: Some(Value::Null),
                },
            },
        );

        let request_id = Uuid::new_v4();
        let response = FlagsResponse::new(false, flags, None, Some(request_id));
        let legacy_response = response.to_legacy();

        // Check that only flag1 with actual payload is included
        assert_eq!(legacy_response.feature_flag_payloads.len(), 2);
        assert!(legacy_response
            .feature_flag_payloads
            .contains_key("flag_with_payload"));
        assert!(!legacy_response.feature_flag_payloads.contains_key("flag2"));
        assert!(legacy_response
            .feature_flag_payloads
            .contains_key("flag_with_null_payload"));

        // Verify the payload value
        assert_eq!(
            legacy_response
                .feature_flag_payloads
                .get("flag_with_payload"),
            Some(&json!({"key": "value"}))
        );
        assert_eq!(
            legacy_response
                .feature_flag_payloads
                .get("flag_with_null_payload"),
            Some(&json!(null))
        );

        // Check that the request_id is included
        assert_eq!(legacy_response.request_id, request_id);
    }

    #[test]
    fn test_config_fields_are_skipped_when_none() {
        let response = FlagsResponse::new(false, HashMap::new(), None, Some(Uuid::new_v4()));

        let json = serde_json::to_value(&response).unwrap();
        let obj = json.as_object().unwrap();

        // Config fields should not be present when None/empty
        assert!(!obj.contains_key("analytics"));
        assert!(!obj.contains_key("autocaptureExceptions"));
        assert!(!obj.contains_key("sessionRecording"));
        assert!(!obj.contains_key("supportedCompression")); // empty vec
        assert!(!obj.contains_key("siteApps")); // empty vec

        // Core fields should always be present
        assert!(obj.contains_key("errorsWhileComputingFlags"));
        assert!(obj.contains_key("flags"));
        assert!(obj.contains_key("featureFlags"));
        assert!(obj.contains_key("featureFlagPayloads"));
    }

    #[test]
    fn test_config_fields_are_included_when_set() {
        let mut response = FlagsResponse::new(false, HashMap::new(), None, Some(Uuid::new_v4()));

        println!("response: {:?}", response);

        // Set some config fields
        response.analytics = Some(AnalyticsConfig {
            endpoint: Some("/analytics".to_string()),
        });
        response.supported_compression = vec!["gzip".to_string()];

        let json = serde_json::to_value(&response).unwrap();

        println!("json: {:?}", json);
        let obj = json.as_object().unwrap();

        // Config fields should be present when set
        assert!(obj.contains_key("analytics"));
        assert!(obj.contains_key("supportedCompression"));
    }
}
