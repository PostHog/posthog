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
#[serde(rename_all = "camelCase")]
pub struct FlagsResponse {
    pub errors_while_computing_flags: bool,
    pub feature_flags: HashMap<String, FlagValue>,
    pub feature_flag_payloads: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>, // list of quota limited resources
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagsOptionsResponse {
    pub status: FlagsResponseCode,
}

/// Properties prepared for feature flag evaluation, containing:
/// - person_property_overrides: Optional properties to override for the person (e.g. geoip data)
/// - group_property_overrides: Optional properties to override for each group
/// - groups: Optional group memberships for the person
/// - hash_key_override: Optional override for the hash key used in flag evaluation
pub type RequestPropertyOverrides = (
    Option<HashMap<String, Value>>, // person_property_overrides
    Option<HashMap<String, HashMap<String, Value>>>, // group_property_overrides
    Option<HashMap<String, Value>>, // groups
    Option<String>,                 // hash_key_override
);
