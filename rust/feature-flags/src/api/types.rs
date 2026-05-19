use crate::api::errors::FlagError;
use crate::flags::flag_match_reason::FeatureFlagMatchReason;
use crate::flags::flag_matching::FeatureFlagMatch;
use crate::flags::flag_models::FeatureFlag;
use crate::properties::property_matching::match_property;
use crate::properties::property_models::OperatorType;
use serde::{de, Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::{collections::HashMap, fmt, str::FromStr};
use uuid::Uuid;

fn format_operator_explanation(key: &str, op_label: &str, value: &Option<Value>) -> String {
    match value {
        Some(v) => format!("Property '{}' {} {}", key, op_label, v),
        None => format!("Property '{}' {} (empty)", key, op_label),
    }
}

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
    pub id: i64,
    pub url: String,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Compression {
    #[serde(alias = "gzip-js")]
    Gzip,
    Base64,
    #[default]
    #[serde(other)]
    Unsupported,
}

impl FromStr for Compression {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "gzip" | "gzip-js" => Ok(Compression::Gzip),
            "base64" => Ok(Compression::Base64),
            _ => Ok(Compression::Unsupported),
        }
    }
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
    #[serde(alias = "v", default, deserialize_with = "empty_string_as_none")]
    pub version: Option<String>,

    /// Compression type for the incoming request
    #[serde(default, deserialize_with = "empty_string_as_none")]
    pub compression: Option<Compression>,

    /// Library version (alias: "ver")
    #[serde(alias = "ver", default, deserialize_with = "empty_string_as_none")]
    pub lib_version: Option<String>,

    /// Optional timestamp indicating when the request was sent
    #[serde(
        alias = "_",
        default,
        deserialize_with = "deserialize_optional_timestamp"
    )]
    pub sent_at: Option<i64>,

    /// Optional boolean indicating whether to only evaluate survey feature flags
    #[serde(default, deserialize_with = "deserialize_optional_bool")]
    pub only_evaluate_survey_feature_flags: Option<bool>,

    /// Optional boolean indicating whether to include the config field in the response
    /// This lets us have parity with the legacy /decide endpoint so that we can support
    /// JS and other mobile clients need more config data than /flags supplied originally.
    /// e.g. https://us.posthog.com/flags?v=2&config=true
    #[serde(default, deserialize_with = "deserialize_optional_bool")]
    pub config: Option<bool>,
    /// Optional boolean indicating whether to include detailed condition analysis in the response
    /// When true, returns detailed information about why each condition matched or didn't match
    /// e.g. https://us.posthog.com/flags?v=2&detailed_analysis=true
    #[serde(default, deserialize_with = "deserialize_optional_bool")]
    pub detailed_analysis: Option<bool>,
    /// Optional boolean indicating whether to only use person properties from the request payload
    /// When true, ignores person properties from the database and only uses properties from person_properties field
    /// Useful for historical evaluation at specific timestamps
    /// e.g. https://us.posthog.com/flags?v=2&only_use_override_person_properties=true
    #[serde(default, deserialize_with = "deserialize_optional_bool")]
    pub only_use_override_person_properties: Option<bool>,
}

#[derive(Debug, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum ServiceResponse {
    Default(LegacyFlagsResponse),
    V2(FlagsResponse),
    DecideV1(DecideV1Response),
    DecideV2(DecideV2Response),
}

/// Config response that passes through Python's cached config as raw JSON.
///
/// This is a thin wrapper around a JSON map that allows Rust to pass through
/// config fields without knowing their structure. Only fields that Rust must
/// modify (like `sessionRecording` for quota limiting) are accessed directly.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize, Default)]
pub struct ConfigResponse {
    #[serde(flatten)]
    inner: HashMap<String, Value>,
}

impl ConfigResponse {
    /// Create an empty config response
    pub fn new() -> Self {
        Self {
            inner: HashMap::new(),
        }
    }

    /// Create a minimal fallback config for cache miss/error scenarios.
    ///
    /// This config disables optional features (session recording, surveys, heatmaps, etc.)
    /// to ensure safe degradation when the full config from Python's HyperCache is unavailable.
    pub fn fallback(api_token: &str, has_feature_flags: bool) -> Self {
        let fallback = serde_json::json!({
            "token": api_token,
            "hasFeatureFlags": has_feature_flags,
            "supportedCompression": ["gzip", "gzip-js"],
            "sessionRecording": false,
            "surveys": false,
            "heatmaps": false,
            "capturePerformance": false,
            "autocaptureExceptions": false,
            "isAuthenticated": false,
            "toolbarParams": {},
            "config": {"enable_collect_everything": true}
        });

        Self::from_value(fallback)
    }

    /// Create from a raw JSON Value (must be an object)
    pub fn from_value(value: Value) -> Self {
        match value {
            Value::Object(map) => Self {
                inner: map.into_iter().collect(),
            },
            _ => Self::new(),
        }
    }

    /// Set a field in the config
    pub fn set(&mut self, key: &str, value: Value) {
        self.inner.insert(key.to_string(), value);
    }

    /// Get a field from the config
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.inner.get(key)
    }

    /// Check if config is empty
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }
}

#[derive(Debug, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlagsResponse {
    /// Whether any errors occurred while evaluating feature flags.
    /// If true, some flags may be missing or have fallback values.
    pub errors_while_computing_flags: bool,
    /// Map of feature flag keys to their evaluation results and values
    pub flags: HashMap<String, FlagDetails>,
    /// List of resource types that hit quota limits during evaluation (e.g., "database", "redis")
    /// Only included in response if quotas were exceeded
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
    /// Unique identifier for this flag evaluation request, useful for debugging and tracing
    pub request_id: Uuid,
    /// Timestamp when flags were evaluated, in milliseconds since Unix epoch
    pub evaluated_at: i64,

    /// Additional configuration data merged into the response at the top level
    #[serde(flatten)]
    pub config: ConfigResponse,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyFlagsResponse {
    pub errors_while_computing_flags: bool,
    pub feature_flags: HashMap<String, FlagValue>,
    pub feature_flag_payloads: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>, // list of quota limited resources
    pub request_id: Uuid,
    pub evaluated_at: i64,

    #[serde(flatten)]
    pub config: ConfigResponse,
}

impl LegacyFlagsResponse {
    pub fn from_response(response: FlagsResponse) -> Self {
        let mut feature_flags = HashMap::with_capacity(response.flags.len());
        let mut feature_flag_payloads = HashMap::with_capacity(response.flags.len());

        for (key, mut flag) in response.flags {
            let payload = flag.metadata.payload.take();
            let flag_value = flag.into_value();
            if let Some(payload) = payload {
                feature_flags.insert(key.clone(), flag_value);
                feature_flag_payloads.insert(key, payload);
            } else {
                feature_flags.insert(key, flag_value);
            }
        }

        Self {
            errors_while_computing_flags: response.errors_while_computing_flags,
            feature_flags,
            feature_flag_payloads,
            quota_limited: response.quota_limited,
            request_id: response.request_id,
            evaluated_at: response.evaluated_at,
            config: response.config,
        }
    }
}

/// Legacy decide v1 format response - returns just a list of active flag keys
#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DecideV1Response {
    pub feature_flags: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
    pub request_id: Uuid,
    pub evaluated_at: i64,

    #[serde(flatten)]
    pub config: ConfigResponse,
}

impl DecideV1Response {
    pub fn from_response(response: FlagsResponse) -> Self {
        // Only include flags that are enabled (active)
        let active_flags: Vec<String> = response
            .flags
            .into_iter()
            .filter(|(_, flag)| flag.enabled)
            .map(|(key, _)| key)
            .collect();

        Self {
            feature_flags: active_flags,
            quota_limited: response.quota_limited,
            request_id: response.request_id,
            evaluated_at: response.evaluated_at,
            config: response.config,
        }
    }
}

/// Legacy decide v2 format response - returns active flags with their values
#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DecideV2Response {
    pub feature_flags: HashMap<String, FlagValue>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
    pub request_id: Uuid,
    pub evaluated_at: i64,

    #[serde(flatten)]
    pub config: ConfigResponse,
}

impl DecideV2Response {
    pub fn from_response(response: FlagsResponse) -> Self {
        // Only include flags that are enabled
        let active_flags: HashMap<String, FlagValue> = response
            .flags
            .into_iter()
            .filter(|(_, flag)| flag.enabled)
            .map(|(key, flag)| (key, flag.into_value()))
            .collect();

        Self {
            feature_flags: active_flags,
            quota_limited: response.quota_limited,
            request_id: response.request_id,
            evaluated_at: response.evaluated_at,
            config: response.config,
        }
    }
}

impl FlagsResponse {
    pub fn new(
        errors_while_computing_flags: bool,
        flags: HashMap<String, FlagDetails>,
        quota_limited: Option<Vec<String>>,
        request_id: Uuid,
    ) -> Self {
        Self {
            errors_while_computing_flags,
            flags,
            quota_limited,
            request_id,
            evaluated_at: chrono::Utc::now().timestamp_millis(),
            config: ConfigResponse::default(),
        }
    }

    /// Test helper to create a FlagsResponse with a specific evaluated_at timestamp
    #[cfg(test)]
    pub fn with_evaluated_at(
        errors_while_computing_flags: bool,
        flags: HashMap<String, FlagDetails>,
        quota_limited: Option<Vec<String>>,
        request_id: Uuid,
        evaluated_at: i64,
    ) -> Self {
        Self {
            errors_while_computing_flags,
            flags,
            quota_limited,
            request_id,
            evaluated_at,
            config: ConfigResponse::default(),
        }
    }
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagsOptionsResponse {
    pub status: FlagsResponseCode,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PropertyAnalysis {
    pub key: String,
    pub operator: String,
    pub value: Value,
    pub r#type: String,
    pub actual_value: Option<Value>,
    pub matched: bool,
    pub explanation: String,
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
pub struct ConditionAnalysis {
    pub index: i32,
    pub properties: Vec<PropertyAnalysis>,
    pub rollout_percentage: f64,
    pub variant: Option<String>,
    /// True when this condition was the one that won (i.e. determined the
    /// flag's enabled/variant outcome). Use this to find the winning condition
    /// in a list — it is guaranteed to be set on at most one condition per flag.
    pub matched: bool,
    /// True when every property in this condition evaluated to true,
    /// regardless of whether this condition was the eventual winner. A later
    /// condition may have won, an earlier one may have short-circuited the
    /// evaluation, or rollout may have excluded this condition entirely.
    pub properties_matched: bool,
    pub rollout_excluded: bool,
    pub explanation: String,
}

#[derive(Debug, PartialEq, Deserialize, Serialize)]
pub struct FlagDetails {
    pub key: String,
    pub enabled: bool,
    pub variant: Option<String>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub failed: bool,
    pub reason: FlagEvaluationReason,
    pub metadata: FlagDetailsMetadata,
    /// Optional detailed condition analysis, only included when requested
    #[serde(skip_serializing_if = "Option::is_none")]
    pub conditions: Option<Vec<ConditionAnalysis>>,
}

impl FlagDetails {
    pub fn to_value(&self) -> FlagValue {
        if let Some(variant) = &self.variant {
            FlagValue::String(variant.clone())
        } else {
            FlagValue::Boolean(self.enabled)
        }
    }

    pub fn into_value(self) -> FlagValue {
        if let Some(variant) = self.variant {
            FlagValue::String(variant)
        } else {
            FlagValue::Boolean(self.enabled)
        }
    }
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
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
    fn create_with_analysis(
        flag: &FeatureFlag,
        flag_match: &FeatureFlagMatch,
        detailed_analysis: bool,
        property_values: Option<&HashMap<String, Value>>,
    ) -> Self;
    fn create_error(flag: &FeatureFlag, error: &FlagError, condition_index: Option<i32>) -> Self;
    fn get_reason_description(match_info: &FeatureFlagMatch) -> Option<String>;
}

impl FromFeatureAndMatch for FlagDetails {
    fn create(flag: &FeatureFlag, flag_match: &FeatureFlagMatch) -> Self {
        Self::create_with_analysis(flag, flag_match, false, None)
    }

    fn create_with_analysis(
        flag: &FeatureFlag,
        flag_match: &FeatureFlagMatch,
        detailed_analysis: bool,
        property_values: Option<&HashMap<String, Value>>,
    ) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: flag_match.matches,
            variant: flag_match.variant.clone(),
            failed: false,
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
            conditions: if detailed_analysis {
                Some(Self::build_condition_analysis(
                    flag,
                    flag_match,
                    property_values,
                ))
            } else {
                None
            },
        }
    }

    fn create_error(flag: &FeatureFlag, error: &FlagError, condition_index: Option<i32>) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: false,
            variant: None,
            failed: true,
            reason: FlagEvaluationReason {
                code: error.evaluation_error_code(),
                condition_index,
                description: Some(error.evaluation_error_description()),
            },
            metadata: FlagDetailsMetadata {
                id: flag.id,
                version: flag.version.unwrap_or(0),
                description: None,
                payload: None,
            },
            conditions: None,
        }
    }

    fn get_reason_description(match_info: &FeatureFlagMatch) -> Option<String> {
        match match_info.reason {
            FeatureFlagMatchReason::ConditionMatch => {
                let set_number = match_info.condition_index.unwrap_or(0) + 1;
                Some(format!("Matched condition set {set_number}"))
            }
            FeatureFlagMatchReason::NoConditionMatch => {
                Some("No matching condition set".to_string())
            }
            FeatureFlagMatchReason::NoConditionMatchGroupsNotEvaluated => {
                Some("No matching condition set (group conditions were not evaluated because no group type was provided)".to_string())
            }
            FeatureFlagMatchReason::OutOfRolloutBound => Some("Out of rollout bound".to_string()),
            FeatureFlagMatchReason::NoGroupType => Some("No group type".to_string()),
            FeatureFlagMatchReason::SuperConditionValue => {
                Some("Super condition value".to_string())
            }
            FeatureFlagMatchReason::HoldoutConditionValue => {
                Some("Holdout condition value".to_string())
            }
            FeatureFlagMatchReason::FlagDisabled => Some("Feature flag is disabled".to_string()),
            FeatureFlagMatchReason::MissingDependency => {
                Some("Flag cannot be evaluated due to missing dependency".to_string())
            }
        }
    }
}

impl FlagDetails {
    fn build_condition_analysis(
        flag: &FeatureFlag,
        flag_match: &FeatureFlagMatch,
        property_values: Option<&HashMap<String, Value>>,
    ) -> Vec<ConditionAnalysis> {
        let mut analyses = Vec::new();

        // Analyze each property group (condition)
        for (index, group) in flag.filters.groups.iter().enumerate() {
            let mut property_analyses = Vec::new();
            let mut condition_matched = false;

            // Determine if this condition matched based on overall flag result and condition index
            // Only mark as matched if the flag itself matched AND this is the matching condition
            if flag_match.matches {
                if let Some(condition_index) = flag_match.condition_index {
                    condition_matched = index == condition_index;
                } else if matches!(flag_match.reason, FeatureFlagMatchReason::ConditionMatch) {
                    // Fallback: assume first condition matched if we have a condition match but no index
                    condition_matched = index == 0;
                }
            }
            // If flag_match.matches is false, condition_matched remains false for all conditions

            // Analyze properties within this group
            if let Some(properties) = &group.properties {
                for property in properties {
                    let operator_str = match property.operator {
                        Some(op) => format!("{:?}", op).to_lowercase(),
                        None => "exact".to_string(),
                    };

                    let type_str = match property.prop_type {
                        crate::properties::property_models::PropertyType::Person => "person",
                        crate::properties::property_models::PropertyType::Group => "group",
                        crate::properties::property_models::PropertyType::Cohort => "cohort",
                        crate::properties::property_models::PropertyType::Flag => "flag",
                    }
                    .to_string();

                    // Generate explanation placeholder - will be updated after we know if property matched
                    let explanation_placeholder = match property.operator {
                        Some(OperatorType::IsSet) => ("is set", "is not set"),
                        Some(OperatorType::IsNotSet) => ("is not set", "is set"),
                        Some(OperatorType::Exact) => ("equals", "does not equal"),
                        Some(OperatorType::IsNot) => ("does not equal", "equals"),
                        Some(OperatorType::Icontains) => ("contains", "does not contain"),
                        Some(OperatorType::NotIcontains) => ("does not contain", "contains"),
                        Some(OperatorType::Gt) => (">", "<="),
                        Some(OperatorType::Lt) => ("<", ">="),
                        Some(OperatorType::Gte) => (">=", "<"),
                        Some(OperatorType::Lte) => ("<=", ">"),
                        Some(OperatorType::In) => ("is in", "is not in"),
                        Some(OperatorType::NotIn) => ("is not in", "is in"),
                        Some(OperatorType::Regex) => ("matches regex", "does not match regex"),
                        Some(OperatorType::NotRegex) => ("does not match regex", "matches regex"),
                        _ => (operator_str.as_str(), "does not match"),
                    };

                    let (property_matched, actual_value) = if let Some(props) = property_values {
                        let actual = props.get(&property.key).cloned();
                        let matched = match_property(property, props, false).unwrap_or(false);
                        (matched, actual)
                    } else {
                        // No properties available, fall back to condition-level match
                        (condition_matched, None)
                    };

                    // Generate the correct explanation based on whether the property matched
                    let explanation = if property_matched {
                        match property.operator {
                            Some(OperatorType::IsSet) | Some(OperatorType::IsNotSet) => {
                                format!("Property '{}' {}", property.key, explanation_placeholder.0)
                            }
                            _ => format_operator_explanation(
                                &property.key,
                                explanation_placeholder.0,
                                &property.value,
                            ),
                        }
                    } else {
                        match property.operator {
                            Some(OperatorType::IsSet) | Some(OperatorType::IsNotSet) => {
                                format!("Property '{}' {}", property.key, explanation_placeholder.1)
                            }
                            _ => format_operator_explanation(
                                &property.key,
                                explanation_placeholder.1,
                                &property.value,
                            ),
                        }
                    };

                    let property_analysis = PropertyAnalysis {
                        key: property.key.clone(),
                        operator: operator_str,
                        value: property.value.clone().unwrap_or(serde_json::Value::Null),
                        r#type: type_str,
                        actual_value,
                        matched: property_matched,
                        explanation,
                    };
                    property_analyses.push(property_analysis);
                }
            }

            // Determine rollout status and properties match status
            let rollout_percentage = group.rollout_percentage.unwrap_or(100.0);
            let is_zero_rollout = rollout_percentage == 0.0;

            // Check if this condition has properties that would need to be evaluated
            let has_properties = group
                .properties
                .as_ref()
                .map(|props| !props.is_empty())
                .unwrap_or(false);

            // Determine if all properties in this condition actually matched
            let all_properties_matched = if has_properties {
                property_analyses.iter().all(|prop| prop.matched)
            } else {
                // If no properties, consider it a match (rollout-only condition)
                true
            };

            // Key insight: Use the overall match reason to determine what happened
            // If reason is OutOfRolloutBound, it means properties matched but rollout failed
            let properties_matched_but_rollout_failed =
                matches!(flag_match.reason, FeatureFlagMatchReason::OutOfRolloutBound);

            // Determine if this specific condition was the one that got excluded by rollout
            let this_condition_rollout_excluded = if properties_matched_but_rollout_failed {
                // If overall reason is OutOfRolloutBound, check if this condition has matching index
                if let Some(match_condition_index) = flag_match.condition_index {
                    // This condition was the one that matched properties but failed rollout
                    index == match_condition_index && is_zero_rollout
                } else {
                    // No specific condition index, so could be this one if it has zero rollout
                    is_zero_rollout && all_properties_matched
                }
            } else {
                // Overall reason is not OutOfRolloutBound, so use simple zero rollout check
                is_zero_rollout && all_properties_matched
            };

            let explanation = if this_condition_rollout_excluded {
                format!(
                    "Condition {} matched properties but was excluded by {}% rollout",
                    index, rollout_percentage
                )
            } else if all_properties_matched && condition_matched {
                format!(
                    "Condition {} matched and passed {}% rollout",
                    index, rollout_percentage
                )
            } else if all_properties_matched && !condition_matched {
                format!(
                    "Condition {} matched properties but was not evaluated due to an earlier condition matching",
                    index
                )
            } else {
                format!("Condition {} did not match properties", index)
            };

            let analysis = ConditionAnalysis {
                index: index as i32,
                properties: property_analyses,
                rollout_percentage,
                variant: group.variant.clone(),
                matched: condition_matched,
                properties_matched: all_properties_matched,
                rollout_excluded: this_condition_rollout_excluded,
                explanation,
            };

            analyses.push(analysis);
        }

        analyses
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AnalyticsConfig {
    pub endpoint: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default, Eq)]
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub record_canvas: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub canvas_fps: Option<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub canvas_quality: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Eq)]
#[serde(untagged)]
pub enum SessionRecordingField {
    Disabled(bool), // NB: this should only ever be false
    Config(Box<SessionRecordingConfig>),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LogsConfig {
    pub capture_console_logs: Option<bool>,
}

impl Default for SessionRecordingField {
    fn default() -> Self {
        SessionRecordingField::Disabled(false)
    }
}

/// Generic deserializer that treats empty strings as None for any type that implements FromStr
fn empty_string_as_none<'de, D, T>(de: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr,
    T::Err: fmt::Display,
{
    let opt = Option::<String>::deserialize(de)?;
    match opt.as_deref() {
        None | Some("") => Ok(None),
        Some(s) => FromStr::from_str(s).map_err(de::Error::custom).map(Some),
    }
}

/// Deserializer for timestamps that handles both strings and integers
fn deserialize_optional_timestamp<'de, D>(de: D) -> Result<Option<i64>, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum IntOrString {
        Int(i64),
        String(String),
    }

    let opt = Option::<IntOrString>::deserialize(de)?;
    match opt {
        None => Ok(None),
        Some(IntOrString::Int(i)) => Ok(Some(i)),
        Some(IntOrString::String(s)) if s.is_empty() => Ok(None),
        Some(IntOrString::String(s)) => s.parse().map(Some).map_err(de::Error::custom),
    }
}

/// Deserializer for boolean query parameters that treats presence as true
/// Examples:
/// - `?config` → Some(true)
/// - `?config=` → Some(true)
/// - `?config=true` → Some(true)
/// - `?config=false` → Some(false)
/// - `?config=1` → Some(true)
/// - `?config=0` → Some(false)
/// - missing → None
fn deserialize_optional_bool<'de, D>(de: D) -> Result<Option<bool>, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum BoolOrString {
        Bool(bool),
        String(String),
    }

    let opt = Option::<BoolOrString>::deserialize(de)?;
    match opt {
        None => Ok(None),
        Some(BoolOrString::Bool(b)) => Ok(Some(b)),
        Some(BoolOrString::String(s)) => {
            match s.to_lowercase().as_str() {
                "" => Ok(Some(true)), // Empty string = present = true
                "true" | "1" | "yes" | "on" => Ok(Some(true)),
                "false" | "0" | "no" | "off" => Ok(Some(false)),
                _ => Ok(Some(true)), // Any other value = true (presence indicates true)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_match_reason::FeatureFlagMatchReason;
    use crate::flags::flag_matching::FeatureFlagMatch;
    use chrono::Utc;
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
    #[case::flag_disabled(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::FlagDisabled,
            condition_index: None,
            payload: None,
        },
        Some("Feature flag is disabled".to_string())
    )]
    #[case::missing_dependency(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::MissingDependency,
            condition_index: None,
            payload: None,
        },
        Some("Flag cannot be evaluated due to missing dependency".to_string())
    )]
    #[case::no_condition_match_groups_not_evaluated(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::NoConditionMatchGroupsNotEvaluated,
            condition_index: Some(0),
            payload: None,
        },
        Some("No matching condition set (group conditions were not evaluated because no group type was provided)".to_string())
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
                failed: false,
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
                conditions: None,
            },
        );

        // Flag without payload
        flags.insert(
            "flag2".to_string(),
            FlagDetails {
                key: "flag2".to_string(),
                enabled: true,
                variant: None,
                failed: false,
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
                conditions: None,
            },
        );

        // Flag with null payload, which should not be filtered out; since Some(Value::Null) is not None
        flags.insert(
            "flag_with_null_payload".to_string(),
            FlagDetails {
                key: "flag_with_null_payload".to_string(),
                enabled: true,
                variant: None,
                failed: false,
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
                conditions: None,
            },
        );

        let request_id = Uuid::new_v4();
        let evaluated_at = Utc::now().timestamp_millis();
        let response =
            FlagsResponse::with_evaluated_at(false, flags, None, request_id, evaluated_at);
        let legacy_response = LegacyFlagsResponse::from_response(response);

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
        let response = FlagsResponse::new(false, HashMap::new(), None, Uuid::new_v4());

        let json = serde_json::to_value(&response).unwrap();
        let obj = json.as_object().unwrap();

        // Config fields should not be present when None/empty
        assert!(!obj.contains_key("analytics"));
        assert!(!obj.contains_key("autocaptureExceptions"));
        assert!(!obj.contains_key("sessionRecording"));

        // Core fields should always be present
        assert!(obj.contains_key("errorsWhileComputingFlags"));
        assert!(obj.contains_key("flags"));
        assert!(obj.contains_key("requestId"));
    }

    #[test]
    fn test_config_fields_are_included_when_set() {
        let mut response = FlagsResponse::new(false, HashMap::new(), None, Uuid::new_v4());

        // Set some config fields using the new passthrough API
        response
            .config
            .set("analytics", json!({"endpoint": "/analytics"}));
        response.config.set("supportedCompression", json!(["gzip"]));

        let json = serde_json::to_value(&response).unwrap();

        let obj = json.as_object().unwrap();

        // Config fields should be present when set
        assert!(obj.contains_key("analytics"));
        assert!(obj.contains_key("supportedCompression"));
    }

    #[test]
    fn test_evaluated_at_field_is_present() {
        let before = Utc::now().timestamp_millis();
        let response = FlagsResponse::new(false, HashMap::new(), None, Uuid::new_v4());
        let after = Utc::now().timestamp_millis();

        let json = serde_json::to_value(&response).unwrap();
        let obj = json.as_object().unwrap();

        // evaluated_at field should always be present
        assert!(obj.contains_key("evaluatedAt"));

        // Verify it's a number and within a reasonable range
        let evaluated_at = obj.get("evaluatedAt").unwrap().as_i64().unwrap();
        assert!(evaluated_at >= before);
        assert!(evaluated_at <= after);
    }

    #[test]
    fn test_condition_analysis_properties_matched_can_diverge_from_matched() {
        use crate::flags::flag_models::FeatureFlag;
        use std::collections::HashMap;

        // Create a flag with two conditions using JSON parsing (same pattern as other tests):
        // Condition 0: properties match but rollout_percentage = 0 (no match)
        // Condition 1: properties match and rollout_percentage = 100 (match)
        let flag: FeatureFlag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": 1,
                "name": "test-flag",
                "key": "test-flag",
                "active": true,
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "test@example.com",
                                    "type": "person"
                                }
                            ],
                            "rollout_percentage": 0
                        },
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "test@example.com",
                                    "type": "person"
                                }
                            ],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        // Create a flag match where condition 1 matched (index 1)
        let flag_match = FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::ConditionMatch,
            condition_index: Some(1),
            payload: None,
        };

        // Create property values that would match both conditions
        let mut property_values = HashMap::new();
        property_values.insert("email".to_string(), serde_json::json!("test@example.com"));

        // Build condition analysis
        let analysis =
            FlagDetails::build_condition_analysis(&flag, &flag_match, Some(&property_values));

        // Verify we have analysis for both conditions
        assert_eq!(analysis.len(), 2);

        // Condition 0: properties matched but overall condition did not match (rollout = 0%)
        assert!(
            analysis[0].properties_matched,
            "Condition 0 should have properties_matched=true"
        );
        assert!(
            !analysis[0].matched,
            "Condition 0 should have matched=false due to 0% rollout"
        );
        assert_eq!(analysis[0].index, 0);
        assert!(
            analysis[0].rollout_excluded,
            "Condition 0 should be rollout_excluded"
        );

        // Condition 1: properties matched and overall condition matched
        assert!(
            analysis[1].properties_matched,
            "Condition 1 should have properties_matched=true"
        );
        assert!(analysis[1].matched, "Condition 1 should have matched=true");
        assert_eq!(analysis[1].index, 1);
        assert!(
            !analysis[1].rollout_excluded,
            "Condition 1 should not be rollout_excluded"
        );
    }
}
