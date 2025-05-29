use crate::flags::flag_match_reason::FeatureFlagMatchReason;
use crate::flags::flag_matching::FeatureFlagMatch;
use crate::flags::flag_models::FeatureFlag;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use uuid::Uuid;

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
    pub request_id: Uuid,
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
                .filter_map(|(key, flag)| {
                    flag.metadata
                        .payload
                        .clone()
                        .map(|payload| (key.clone(), payload))
                })
                .collect(),
            quota_limited: response.quota_limited,
            request_id: response.request_id,
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
        let response = FlagsResponse::new(false, flags, None, request_id);
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
}
