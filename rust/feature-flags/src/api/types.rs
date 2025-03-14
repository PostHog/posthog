use crate::flags::flag_matching::FeatureFlagMatch;
use crate::flags::flag_models::FeatureFlag;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum FlagsResponseCode {
    Ok = 1,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum FlagValue {
    Boolean(bool),
    String(String),
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum ServiceResponse {
    Default(LegacyFlagsResponse),
    V2(FlagsResponse),
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlagsResponse {
    pub errors_while_computing_flags: bool,
    pub flags: HashMap<String, FlagDetails>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>, // list of quota limited resources
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyFlagsResponse {
    pub errors_while_computing_flags: bool,
    pub feature_flags: HashMap<String, FlagValue>,
    pub feature_flag_payloads: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>, // list of quota limited resources
}

impl LegacyFlagsResponse {
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
                .map(|(key, flag)| {
                    (
                        key.clone(),
                        flag.metadata.payload.clone().unwrap_or(Value::Null),
                    )
                })
                .collect(),
            quota_limited: response.quota_limited,
        }
    }
}

impl FlagsResponse {
    pub fn new(
        errors_while_computing_flags: bool,
        flags: HashMap<String, FlagDetails>,
        quota_limited: Option<Vec<String>>,
    ) -> Self {
        Self {
            errors_while_computing_flags,
            flags,
            quota_limited,
        }
    }
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagsOptionsResponse {
    pub status: FlagsResponseCode,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagDetails {
    pub key: String,
    pub enabled: bool,
    pub variant: String,
    pub reason: FlagEvaluationReason,
    pub metadata: FlagDetailsMetadata,
}

impl FlagDetails {
    pub fn to_value(&self) -> FlagValue {
        if !self.variant.is_empty() {
            FlagValue::String(self.variant.clone())
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

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagEvaluationReason {
    pub code: String,
    pub condition_index: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

pub trait FromFeatureAndMatch {
    fn create(flag: &FeatureFlag, flag_match: &FeatureFlagMatch) -> Self;
    fn create_error(flag: &FeatureFlag, error_reason: &str) -> Self;
}

impl FromFeatureAndMatch for FlagDetails {
    fn create(flag: &FeatureFlag, flag_match: &FeatureFlagMatch) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: flag_match.matches,
            variant: flag_match.variant.clone().unwrap_or_default(),
            reason: FlagEvaluationReason {
                code: flag_match.reason.to_string(),
                condition_index: flag_match.condition_index.map(|i| i as i32),
                description: None,
            },
            metadata: FlagDetailsMetadata {
                id: flag.id,
                version: flag.version.unwrap_or(0),
                description: flag.name.clone(),
                payload: flag_match.payload.clone(),
            },
        }
    }

    fn create_error(flag: &FeatureFlag, error_reason: &str) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: false,
            variant: "".to_string(),
            reason: FlagEvaluationReason {
                code: error_reason.to_string(),
                condition_index: None,
                description: None,
            },
            metadata: FlagDetailsMetadata {
                id: flag.id,
                version: flag.version.unwrap_or(0),
                description: flag.name.clone(),
                payload: None,
            },
        }
    }
}
