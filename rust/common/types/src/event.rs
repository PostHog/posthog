use std::collections::HashMap;
use std::ops::Not;

use crate::util::{empty_datetime_is_none, empty_string_uuid_is_none};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use uuid::Uuid;

/// Information about the library/SDK that sent an event
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LibraryInfo {
    pub name: String,
    pub version: Option<String>,
}

#[derive(Default, Debug, Deserialize, Serialize)]
pub struct RawEvent {
    #[serde(
        alias = "$token",
        alias = "api_key",
        skip_serializing_if = "Option::is_none"
    )]
    pub token: Option<String>,
    #[serde(alias = "$distinct_id", skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<Value>, // posthog-js accepts arbitrary values as distinct_id
    #[serde(default, deserialize_with = "empty_string_uuid_is_none")]
    pub uuid: Option<Uuid>,
    pub event: String,
    #[serde(default)]
    pub properties: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>, // Passed through if provided, parsed by ingestion
    #[serde(skip_serializing_if = "Option::is_none")]
    pub offset: Option<i64>, // Passed through if provided, parsed by ingestion
    #[serde(rename = "$set", skip_serializing_if = "Option::is_none")]
    pub set: Option<HashMap<String, Value>>,
    #[serde(rename = "$set_once", skip_serializing_if = "Option::is_none")]
    pub set_once: Option<HashMap<String, Value>>,
}

#[derive(Default, Debug, Deserialize, Serialize)]
pub struct RawEngageEvent {
    #[serde(
        alias = "$token",
        alias = "api_key",
        skip_serializing_if = "Option::is_none"
    )]
    pub token: Option<String>,
    #[serde(alias = "$distinct_id", skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<Value>, // posthog-js accepts arbitrary values as distinct_id
    #[serde(default, deserialize_with = "empty_string_uuid_is_none")]
    pub uuid: Option<Uuid>,
    // NOTE: missing event name is the only difference between RawEvent and RawEngageEvent
    // when the event name is missing, we need fill in $identify as capture.py does:
    // https://github.com/PostHog/posthog/blob/70ce86a73f6c3d3ee6f44e1ac0acd695e2f78682/posthog/api/capture.py#L501-L502
    #[serde(default)]
    pub properties: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>, // Passed through if provided, parsed by ingestion
    #[serde(skip_serializing_if = "Option::is_none")]
    pub offset: Option<i64>, // Passed through if provided, parsed by ingestion
    #[serde(rename = "$set", skip_serializing_if = "Option::is_none")]
    pub set: Option<HashMap<String, Value>>,
    #[serde(rename = "$set_once", skip_serializing_if = "Option::is_none")]
    pub set_once: Option<HashMap<String, Value>>,
}

// The event type that capture produces
#[derive(Clone, Debug, Serialize, Deserialize, Eq, PartialEq)]
pub struct CapturedEvent {
    pub uuid: Uuid,
    pub distinct_id: String,
    pub ip: String,
    pub data: String, // This should be a `RawEvent`, but we serialise twice.
    pub now: String,
    #[serde(
        serialize_with = "time::serde::rfc3339::option::serialize",
        deserialize_with = "empty_datetime_is_none",
        skip_serializing_if = "Option::is_none",
        default
    )]
    pub sent_at: Option<OffsetDateTime>,
    pub token: String,
    #[serde(skip_serializing_if = "<&bool>::not", default)]
    pub is_cookieless_mode: bool,
}

// Used when we want to bypass token checks when emitting events from rust
// services, by just setting the team_id instead.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InternallyCapturedEvent {
    #[serde(flatten)]
    pub inner: CapturedEvent,
    pub team_id: i32,
}

impl CapturedEvent {
    pub fn key(&self) -> String {
        if self.is_cookieless_mode {
            format!("{}:{}", self.token, self.ip)
        } else {
            format!("{}:{}", self.token, self.distinct_id)
        }
    }
}

#[derive(Debug, Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "snake_case")]
pub enum PersonMode {
    Full,
    Propertyless,
    ForceUpgrade,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ClickHouseEvent {
    pub uuid: Uuid,
    pub team_id: i32,
    // NOTE - option - this is a nullable column in the DB, so :shrug:
    pub project_id: Option<i64>,
    pub event: String,
    pub distinct_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub person_id: Option<String>,
    // TODO: verify timestamp format
    pub timestamp: String,
    // TODO: verify timestamp format
    pub created_at: String,
    pub elements_chain: Option<String>,
    // TODO: verify timestamp format
    #[serde(skip_serializing_if = "Option::is_none")]
    pub person_created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub person_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group0_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group1_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group2_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group3_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group4_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group0_created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group1_created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group2_created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group3_created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group4_created_at: Option<String>,
    pub person_mode: PersonMode,
}

impl ClickHouseEvent {
    pub fn take_raw_properties(&mut self) -> Result<HashMap<String, Value>, serde_json::Error> {
        // Sometimes properties are REALLY big, so we may as well do this.
        let props_str = self.properties.take();
        let parsed = match &props_str {
            Some(properties) => serde_json::from_str(properties),
            None => Ok(HashMap::new()),
        };

        match parsed {
            Ok(properties) => Ok(properties),
            Err(e) => {
                self.properties = props_str;
                Err(e)
            }
        }
    }

    pub fn set_raw_properties(
        &mut self,
        properties: HashMap<String, Value>,
    ) -> Result<(), serde_json::Error> {
        self.properties = Some(serde_json::to_string(&properties)?);
        Ok(())
    }
}

impl RawEvent {
    pub fn extract_token(&self) -> Option<String> {
        match &self.token {
            Some(value) => Some(value.clone()),
            None => self
                .properties
                .get("token")
                .and_then(Value::as_str)
                .map(String::from),
        }
    }

    /// Extracts, stringifies and trims the distinct_id to a 200 chars String.
    /// SDKs send the distinct_id either in the root field or as a property,
    /// and can send string, number, array, or map values. We try to best-effort
    /// stringify complex values, and make sure it's not longer than 200 chars.
    pub fn extract_distinct_id(&self) -> Option<String> {
        // Breaking change compared to capture-py: None / Null is not allowed.
        let value = match &self.distinct_id {
            None | Some(Value::Null) => match self.properties.get("distinct_id") {
                None | Some(Value::Null) => return None,
                Some(id) => id,
            },
            Some(id) => id,
        };

        let distinct_id = value
            .as_str()
            .map(|s| s.to_owned())
            .unwrap_or_else(|| value.to_string());

        // Replace null characters with Unicode replacement character
        let distinct_id = distinct_id.replace('\0', "\u{FFFD}");

        match distinct_id.len() {
            0 => None,
            1..=200 => Some(distinct_id),
            _ => Some(distinct_id.chars().take(200).collect()),
        }
    }

    // Extracts the cookieless mode from the event properties. If the value is not
    // present, it is assumed to be false, and if it is some invalid value then we
    // return None.
    pub fn extract_is_cookieless_mode(&self) -> Option<bool> {
        match self.properties.get("$cookieless_mode") {
            Some(Value::Bool(b)) => Some(*b),
            Some(_) => None,
            None => Some(false),
        }
    }

    pub fn map_property<F>(&mut self, key: &str, f: F)
    where
        F: FnOnce(Value) -> Value,
    {
        if let Some(value) = self.properties.get_mut(key) {
            *value = f(value.take());
        }
    }

    /// Extract library information from the event properties
    /// Returns None if $lib property is not present
    pub fn extract_library_info(&self) -> Option<LibraryInfo> {
        let name = self
            .properties
            .get("$lib")
            .and_then(|v| v.as_str())
            .map(String::from)?;

        let version = self
            .properties
            .get("$lib_version")
            .and_then(|v| v.as_str())
            .map(String::from);

        Some(LibraryInfo { name, version })
    }
}

impl CapturedEvent {
    pub fn get_sent_at_as_rfc3339(&self) -> Option<String> {
        self.sent_at
            .map(|sa| sa.format(&Rfc3339).expect("is a valid datetime"))
    }
}
