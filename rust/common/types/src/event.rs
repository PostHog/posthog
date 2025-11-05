use std::collections::HashMap;
use std::ops::Not;

use crate::util::{empty_datetime_is_none, empty_string_uuid_is_none};
use chrono::{DateTime, Utc};
use rdkafka::message::{Header, Headers, OwnedHeaders};
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
    #[serde(alias = "$jwt", skip_serializing_if = "Option::is_none")]
    pub jwt: Option<String>,
    #[serde(alias = "$clock_skew", skip_serializing_if = "Option::is_none")]
    pub clock_skew: Option<i64>, // Clock skew in milliseconds
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
    #[serde(alias = "$jwt", skip_serializing_if = "Option::is_none")]
    pub jwt: Option<String>,
    #[serde(alias = "$clock_skew", skip_serializing_if = "Option::is_none")]
    pub clock_skew: Option<i64>, // Clock skew in milliseconds
}

#[derive(Clone)]
pub struct CapturedEventHeaders {
    pub token: Option<String>,
    pub distinct_id: Option<String>,
    pub timestamp: Option<String>,
    pub event: Option<String>,
    pub uuid: Option<String>,
    pub now: Option<String>,
    pub force_disable_person_processing: Option<bool>,
    pub historical_migration: Option<bool>,
    pub jwt: Option<String>,
}

impl CapturedEventHeaders {
    pub fn set_force_disable_person_processing(&mut self, value: bool) {
        self.force_disable_person_processing = Some(value);
    }
}

impl From<CapturedEventHeaders> for OwnedHeaders {
    fn from(headers: CapturedEventHeaders) -> Self {
        let fdpp_str = headers
            .force_disable_person_processing
            .map(|b| b.to_string());
        let historical_migration_str = headers.historical_migration.map(|b| b.to_string());
        OwnedHeaders::new()
            .insert(Header {
                key: "token",
                value: headers.token.as_deref(),
            })
            .insert(Header {
                key: "distinct_id",
                value: headers.distinct_id.as_deref(),
            })
            .insert(Header {
                key: "timestamp",
                value: headers.timestamp.as_deref(),
            })
            .insert(Header {
                key: "event",
                value: headers.event.as_deref(),
            })
            .insert(Header {
                key: "uuid",
                value: headers.uuid.as_deref(),
            })
            .insert(Header {
                key: "now",
                value: headers.now.as_deref(),
            })
            .insert(Header {
                key: "force_disable_person_processing",
                value: fdpp_str.as_deref(),
            })
            .insert(Header {
                key: "historical_migration",
                value: historical_migration_str.as_deref(),
            })
            .insert(Header {
                key: "jwt",
                value: headers.jwt.as_deref(),
            })
    }
}

impl From<OwnedHeaders> for CapturedEventHeaders {
    fn from(headers: OwnedHeaders) -> Self {
        let mut headers_map = HashMap::new();
        for header in headers.iter() {
            if let Some(value) = header.value {
                if let Ok(value_str) = std::str::from_utf8(value) {
                    headers_map.insert(header.key.to_string(), value_str.to_string());
                }
            }
        }

        Self {
            token: headers_map.get("token").cloned(),
            distinct_id: headers_map.get("distinct_id").cloned(),
            timestamp: headers_map.get("timestamp").cloned(),
            event: headers_map.get("event").cloned(),
            uuid: headers_map.get("uuid").cloned(),
            now: headers_map.get("now").cloned(),
            force_disable_person_processing: headers_map
                .get("force_disable_person_processing")
                .and_then(|v| v.parse::<bool>().ok()),
            historical_migration: headers_map
                .get("historical_migration")
                .and_then(|v| v.parse::<bool>().ok()),
            jwt: headers_map.get("jwt").cloned(),
        }
    }
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
    pub event: String,
    pub timestamp: DateTime<Utc>,
    #[serde(skip_serializing_if = "<&bool>::not", default)]
    pub is_cookieless_mode: bool,
    #[serde(skip_serializing_if = "<&bool>::not", default)]
    pub historical_migration: bool,
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
    pub fn to_headers(&self) -> CapturedEventHeaders {
        CapturedEventHeaders {
            token: Some(self.token.clone()),
            distinct_id: Some(self.distinct_id.clone()),
            timestamp: Some(self.timestamp.timestamp_millis().to_string()),
            event: Some(self.event.clone()),
            uuid: Some(self.uuid.to_string()),
            now: Some(self.now.clone()),
            force_disable_person_processing: None, // Only set when explicitly needed (e.g., overflow)
            // Only include historical_migration if true; false is the default
            historical_migration: if self.historical_migration {
                Some(true)
            } else {
                None
            },
            jwt: None, // Set from metadata in kafka sink
        }
    }

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

    /// Extract JWT from the event
    /// Returns the jwt field value
    pub fn extract_jwt(&self) -> Option<String> {
        self.jwt.clone()
    }

    /// Extract clock skew from the event
    /// Returns the clock_skew field value in milliseconds
    pub fn extract_clock_skew(&self) -> Option<i64> {
        self.clock_skew
    }

    /// Normalize the event by extracting jwt and clock_skew from properties
    /// and moving them to top-level fields. Also removes them from properties.
    pub fn normalize(&mut self) {
        // Extract $jwt from properties if not already set at top level
        if self.jwt.is_none() {
            if let Some(Value::String(jwt)) = self.properties.remove("$jwt") {
                self.jwt = Some(jwt);
            }
        } else {
            // If jwt is already set at top level, still remove from properties
            self.properties.remove("$jwt");
        }

        // Extract $clock_skew from properties if not already set at top level
        if self.clock_skew.is_none() {
            if let Some(clock_skew_value) = self.properties.remove("$clock_skew") {
                if let Some(clock_skew) = clock_skew_value.as_i64() {
                    self.clock_skew = Some(clock_skew);
                }
            }
        } else {
            // If clock_skew is already set at top level, still remove from properties
            self.properties.remove("$clock_skew");
        }
    }
}

impl CapturedEvent {
    pub fn get_sent_at_as_rfc3339(&self) -> Option<String> {
        self.sent_at
            .map(|sa| sa.format(&Rfc3339).expect("is a valid datetime"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_captured_event_serialization_with_historical_migration_true() {
        let event = CapturedEvent {
            uuid: Uuid::nil(),
            distinct_id: "test_user".to_string(),
            ip: "127.0.0.1".to_string(),
            data: r#"{"event":"test_event"}"#.to_string(),
            now: "2023-01-02T10:00:00Z".to_string(), // Ingestion time
            sent_at: None,
            token: "test_token".to_string(),
            event: "test_event".to_string(),
            timestamp: DateTime::parse_from_rfc3339("2023-01-01T12:00:00Z") // Event time (earlier)
                .unwrap()
                .with_timezone(&Utc),
            is_cookieless_mode: false,
            historical_migration: true,
        };

        let serialized = serde_json::to_string(&event).expect("Failed to serialize");
        assert!(serialized.contains("\"historical_migration\":true"));

        // Deserialize and verify
        let deserialized: CapturedEvent =
            serde_json::from_str(&serialized).expect("Failed to deserialize");
        assert!(deserialized.historical_migration);
    }

    #[test]
    fn test_captured_event_serialization_with_historical_migration_false() {
        let event = CapturedEvent {
            uuid: Uuid::nil(),
            distinct_id: "test_user".to_string(),
            ip: "127.0.0.1".to_string(),
            data: r#"{"event":"test_event"}"#.to_string(),
            now: "2023-01-02T15:30:00Z".to_string(), // Ingestion time
            sent_at: None,
            token: "test_token".to_string(),
            event: "test_event".to_string(),
            timestamp: DateTime::parse_from_rfc3339("2023-01-02T15:25:00Z") // Event time (5 min earlier)
                .unwrap()
                .with_timezone(&Utc),
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let serialized = serde_json::to_string(&event).expect("Failed to serialize");
        // Should not be in JSON when false (skip_serializing_if)
        assert!(!serialized.contains("historical_migration"));

        // Deserialize and verify - should default to false
        let deserialized: CapturedEvent =
            serde_json::from_str(&serialized).expect("Failed to deserialize");
        assert!(!deserialized.historical_migration);
    }

    #[test]
    fn test_captured_event_deserialization_without_historical_migration() {
        let json = r#"{
            "uuid": "00000000-0000-0000-0000-000000000000",
            "distinct_id": "test_user",
            "ip": "127.0.0.1",
            "data": "{\"event\":\"test_event\"}",
            "now": "2023-01-03T18:00:00Z",
            "token": "test_token",
            "event": "test_event",
            "timestamp": "2023-01-03T17:45:00Z",
            "is_cookieless_mode": false
        }"#;

        let deserialized: CapturedEvent =
            serde_json::from_str(json).expect("Failed to deserialize");
        // Should default to false when not present
        assert!(!deserialized.historical_migration);
    }

    #[test]
    fn test_extract_jwt_present() {
        let event = RawEvent {
            token: None,
            distinct_id: None,
            uuid: None,
            event: "test_event".to_string(),
            properties: HashMap::new(),
            timestamp: None,
            offset: None,
            set: None,
            set_once: None,
            jwt: Some("test-jwt-token".to_string()),
            clock_skew: None,
        };

        assert_eq!(event.extract_jwt(), Some("test-jwt-token".to_string()));
    }

    #[test]
    fn test_extract_jwt_missing() {
        let event = RawEvent {
            token: None,
            distinct_id: None,
            uuid: None,
            event: "test_event".to_string(),
            properties: HashMap::new(),
            timestamp: None,
            offset: None,
            set: None,
            set_once: None,
            jwt: None,
            clock_skew: None,
        };

        assert_eq!(event.extract_jwt(), None);
    }

    #[test]
    fn test_extract_clock_skew_present() {
        let event = RawEvent {
            token: None,
            distinct_id: None,
            uuid: None,
            event: "test_event".to_string(),
            properties: HashMap::new(),
            timestamp: None,
            offset: None,
            set: None,
            set_once: None,
            jwt: None,
            clock_skew: Some(5000),
        };

        assert_eq!(event.extract_clock_skew(), Some(5000));
    }

    #[test]
    fn test_extract_clock_skew_negative() {
        let event = RawEvent {
            token: None,
            distinct_id: None,
            uuid: None,
            event: "test_event".to_string(),
            properties: HashMap::new(),
            timestamp: None,
            offset: None,
            set: None,
            set_once: None,
            jwt: None,
            clock_skew: Some(-3000),
        };

        assert_eq!(event.extract_clock_skew(), Some(-3000));
    }

    #[test]
    fn test_extract_clock_skew_missing() {
        let event = RawEvent {
            token: None,
            distinct_id: None,
            uuid: None,
            event: "test_event".to_string(),
            properties: HashMap::new(),
            timestamp: None,
            offset: None,
            set: None,
            set_once: None,
            jwt: None,
            clock_skew: None,
        };

        assert_eq!(event.extract_clock_skew(), None);
    }

    #[test]
    fn test_captured_event_headers_with_jwt() {
        let headers = CapturedEventHeaders {
            token: Some("test-token".to_string()),
            distinct_id: Some("user-123".to_string()),
            timestamp: Some("1234567890".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("550e8400-e29b-41d4-a716-446655440000".to_string()),
            now: Some("2023-01-01T12:00:00Z".to_string()),
            force_disable_person_processing: None,
            historical_migration: None,
            jwt: Some("test-jwt-token".to_string()),
        };

        let owned_headers: OwnedHeaders = headers.clone().into();
        let headers_back: CapturedEventHeaders = owned_headers.into();

        assert_eq!(headers_back.jwt, Some("test-jwt-token".to_string()));
    }

    #[test]
    fn test_captured_event_headers_without_jwt() {
        let headers = CapturedEventHeaders {
            token: Some("test-token".to_string()),
            distinct_id: Some("user-123".to_string()),
            timestamp: Some("1234567890".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("550e8400-e29b-41d4-a716-446655440000".to_string()),
            now: Some("2023-01-01T12:00:00Z".to_string()),
            force_disable_person_processing: None,
            historical_migration: None,
            jwt: None,
        };

        let owned_headers: OwnedHeaders = headers.clone().into();
        let headers_back: CapturedEventHeaders = owned_headers.into();

        assert_eq!(headers_back.jwt, None);
    }

    #[test]
    fn test_raw_event_json_serialization_with_jwt_and_clock_skew() {
        let mut properties = HashMap::new();
        properties.insert("test_prop".to_string(), Value::String("test_value".to_string()));

        let event = RawEvent {
            token: Some("test-token".to_string()),
            distinct_id: Some(Value::String("user-123".to_string())),
            uuid: None,
            event: "test_event".to_string(),
            properties,
            timestamp: Some("2023-01-01T12:00:00Z".to_string()),
            offset: None,
            set: None,
            set_once: None,
            jwt: Some("test-jwt-token".to_string()),
            clock_skew: Some(5000),
        };

        let serialized = serde_json::to_string(&event).expect("Failed to serialize");
        assert!(serialized.contains("\"jwt\":\"test-jwt-token\""));
        assert!(serialized.contains("\"clock_skew\":5000"));

        let deserialized: RawEvent = serde_json::from_str(&serialized).expect("Failed to deserialize");
        assert_eq!(deserialized.jwt, Some("test-jwt-token".to_string()));
        assert_eq!(deserialized.clock_skew, Some(5000));
    }

    #[test]
    fn test_raw_event_json_deserialization_without_jwt_and_clock_skew() {
        let json = r#"{
            "event": "test_event",
            "properties": {"test_prop": "test_value"},
            "timestamp": "2023-01-01T12:00:00Z"
        }"#;

        let deserialized: RawEvent = serde_json::from_str(json).expect("Failed to deserialize");
        assert_eq!(deserialized.jwt, None);
        assert_eq!(deserialized.clock_skew, None);
    }

    #[test]
    fn test_normalize_extracts_jwt_from_properties() {
        let json = r#"{
            "event": "test_event",
            "properties": {
                "$jwt": "test-jwt-token",
                "other_prop": "value"
            }
        }"#;

        let mut event: RawEvent = serde_json::from_str(json).expect("Failed to deserialize");

        // Before normalization, jwt should be None
        assert_eq!(event.jwt, None);
        assert!(event.properties.contains_key("$jwt"));

        // Normalize the event
        event.normalize();

        // After normalization, jwt should be extracted
        assert_eq!(event.jwt, Some("test-jwt-token".to_string()));
        // And removed from properties
        assert!(!event.properties.contains_key("$jwt"));
        // Other properties should remain
        assert_eq!(event.properties.get("other_prop").and_then(|v| v.as_str()), Some("value"));
    }

    #[test]
    fn test_normalize_extracts_clock_skew_from_properties() {
        let json = r#"{
            "event": "test_event",
            "properties": {
                "$clock_skew": 5000,
                "other_prop": "value"
            }
        }"#;

        let mut event: RawEvent = serde_json::from_str(json).expect("Failed to deserialize");

        // Before normalization
        assert_eq!(event.clock_skew, None);
        assert!(event.properties.contains_key("$clock_skew"));

        // Normalize
        event.normalize();

        // After normalization
        assert_eq!(event.clock_skew, Some(5000));
        assert!(!event.properties.contains_key("$clock_skew"));
        assert_eq!(event.properties.get("other_prop").and_then(|v| v.as_str()), Some("value"));
    }

    #[test]
    fn test_normalize_extracts_both_jwt_and_clock_skew() {
        let json = r#"{
            "event": "test_event",
            "properties": {
                "$jwt": "test-jwt-token",
                "$clock_skew": -3000,
                "user_id": "123"
            }
        }"#;

        let mut event: RawEvent = serde_json::from_str(json).expect("Failed to deserialize");

        event.normalize();

        assert_eq!(event.jwt, Some("test-jwt-token".to_string()));
        assert_eq!(event.clock_skew, Some(-3000));
        assert!(!event.properties.contains_key("$jwt"));
        assert!(!event.properties.contains_key("$clock_skew"));
        assert_eq!(event.properties.get("user_id").and_then(|v| v.as_str()), Some("123"));
    }

    #[test]
    fn test_normalize_preserves_top_level_fields() {
        let json = r#"{
            "event": "test_event",
            "jwt": "top-level-jwt",
            "clock_skew": 1000,
            "properties": {
                "$jwt": "properties-jwt",
                "$clock_skew": 2000
            }
        }"#;

        let mut event: RawEvent = serde_json::from_str(json).expect("Failed to deserialize");

        event.normalize();

        // Top-level fields should be preserved, not overwritten by properties
        assert_eq!(event.jwt, Some("top-level-jwt".to_string()));
        assert_eq!(event.clock_skew, Some(1000));
        // Properties should still be removed
        assert!(!event.properties.contains_key("$jwt"));
        assert!(!event.properties.contains_key("$clock_skew"));
    }
}
