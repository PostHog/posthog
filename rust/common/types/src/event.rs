use std::collections::HashMap;
use std::ops::Not;

use crate::util::{empty_datetime_is_none, empty_string_uuid_is_none};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use uuid::Uuid;

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

// Common fields shared between external and internal events
#[derive(Clone, Debug, Serialize, Deserialize, Eq, PartialEq)]
pub struct CapturedEventCommon {
    pub uuid: Uuid,
    pub distinct_id: String,
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

/// Represents a captured event that can be either internal (from PostHog services)
/// or external (from SDKs/clients).
///
/// This uses an untagged enum for automatic deserialization based on field presence.
/// The deserialization precedence rules are:
///
/// **Internal variant** is selected when:
///    - `team_id` field is present (regardless of IP value)
///    - IP can be null, non-null, or missing
///    - Used by plugin-server and other internal services
///
/// **External variant** is selected when:
///    - `team_id` field is absent
///    - IP must be present and non-null (required field)
///    - Used by capture service for SDK events
///
/// The order of variants in the enum matters for untagged deserialization:
/// serde tries variants in order until one successfully deserializes.
/// Internal is listed first to handle the more specific case (has team_id).
///
/// # Examples
///
/// Internal event (from internal service):
/// ```json
/// {
///   "uuid": "...",
///   "distinct_id": "user123",
///   "ip": null,  // Can be null for internal events
///   "team_id": 123,
///   // ... other fields
/// }
/// ```
///
/// External event (from SDK):
/// ```json
/// {
///   "uuid": "...",
///   "distinct_id": "user123",
///   "ip": "192.168.1.1",  // Required and non-null
///   // No team_id field
///   // ... other fields
/// }
/// ```
#[derive(Clone, Debug, Serialize, Deserialize, Eq, PartialEq)]
#[serde(untagged)]
pub enum CapturedEvent {
    // Internal events (with team_id) can have null IP
    // Listed first for deserialization precedence - more specific case
    Internal {
        #[serde(flatten)]
        common: CapturedEventCommon,
        ip: Option<String>,
        team_id: i32,
    },
    // External events (without team_id) must have IP
    // Listed second - will be tried if Internal variant fails to deserialize
    External {
        #[serde(flatten)]
        common: CapturedEventCommon,
        ip: String,
    },
}

impl CapturedEvent {
    /// Private helper to access common fields
    fn common(&self) -> &CapturedEventCommon {
        match self {
            CapturedEvent::Internal { common, .. } | CapturedEvent::External { common, .. } => {
                common
            }
        }
    }

    /// Constructor for external events (backwards compatibility)
    #[allow(clippy::too_many_arguments)]
    pub fn new_external(
        uuid: Uuid,
        distinct_id: String,
        ip: String,
        data: String,
        now: String,
        sent_at: Option<OffsetDateTime>,
        token: String,
        is_cookieless_mode: bool,
    ) -> Self {
        CapturedEvent::External {
            common: CapturedEventCommon {
                uuid,
                distinct_id,
                data,
                now,
                sent_at,
                token,
                is_cookieless_mode,
            },
            ip,
        }
    }

    /// Constructor for internal events  
    #[allow(clippy::too_many_arguments)]
    pub fn new_internal(
        uuid: Uuid,
        distinct_id: String,
        ip: Option<String>,
        data: String,
        now: String,
        sent_at: Option<OffsetDateTime>,
        token: String,
        is_cookieless_mode: bool,
        team_id: i32,
    ) -> Self {
        CapturedEvent::Internal {
            common: CapturedEventCommon {
                uuid,
                distinct_id,
                data,
                now,
                sent_at,
                token,
                is_cookieless_mode,
            },
            ip,
            team_id,
        }
    }

    pub fn key(&self) -> String {
        if self.is_cookieless_mode() {
            format!("{}:{}", self.token(), self.ip().unwrap_or(""))
        } else {
            format!("{}:{}", self.token(), self.distinct_id())
        }
    }

    // Helper methods to access common fields
    pub fn uuid(&self) -> &Uuid {
        &self.common().uuid
    }

    pub fn distinct_id(&self) -> &str {
        &self.common().distinct_id
    }

    pub fn data(&self) -> &str {
        &self.common().data
    }

    pub fn token(&self) -> &str {
        &self.common().token
    }

    pub fn now(&self) -> &str {
        &self.common().now
    }

    pub fn sent_at(&self) -> Option<OffsetDateTime> {
        self.common().sent_at
    }

    pub fn is_cookieless_mode(&self) -> bool {
        self.common().is_cookieless_mode
    }

    pub fn ip(&self) -> Option<&str> {
        match self {
            CapturedEvent::Internal { ip, .. } => ip.as_deref(),
            CapturedEvent::External { ip, .. } => Some(ip.as_str()),
        }
    }

    pub fn team_id(&self) -> Option<i32> {
        match self {
            CapturedEvent::Internal { team_id, .. } => Some(*team_id),
            CapturedEvent::External { .. } => None,
        }
    }

    pub fn is_internal(&self) -> bool {
        matches!(self, CapturedEvent::Internal { .. })
    }

    pub fn get_sent_at_as_rfc3339(&self) -> Option<String> {
        self.common()
            .sent_at
            .map(|sa| sa.format(&Rfc3339).expect("is a valid datetime"))
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_deserialize_external_event_with_required_ip() {
        // JSON with all fields and a non-null IP (external event)
        let json_str = r#"{
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "distinct_id": "user123",
            "ip": "192.168.1.1",
            "data": "{\"event\": \"test\"}",
            "now": "2024-01-01T00:00:00Z",
            "sent_at": null,
            "token": "test_token",
            "is_cookieless_mode": false
        }"#;

        let event: CapturedEvent = serde_json::from_str(json_str).unwrap();

        // Should deserialize as External variant
        assert!(matches!(event, CapturedEvent::External { .. }));
        assert_eq!(event.ip(), Some("192.168.1.1"));
        assert_eq!(event.team_id(), None);
        assert_eq!(event.token(), "test_token");
        assert_eq!(event.distinct_id(), "user123");
    }

    #[test]
    fn test_deserialize_internal_event_with_null_ip() {
        // JSON with team_id and null IP (internal event)
        let json_str = r#"{
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "distinct_id": "user123",
            "ip": null,
            "data": "{\"event\": \"test\"}",
            "now": "2024-01-01T00:00:00Z",
            "sent_at": null,
            "token": "test_token",
            "is_cookieless_mode": false,
            "team_id": 123
        }"#;

        let event: CapturedEvent = serde_json::from_str(json_str).unwrap();

        // Should deserialize as Internal variant
        assert!(matches!(event, CapturedEvent::Internal { .. }));
        assert_eq!(event.ip(), None);
        assert_eq!(event.team_id(), Some(123));
        assert_eq!(event.token(), "test_token");
        assert_eq!(event.distinct_id(), "user123");
    }

    #[test]
    fn test_deserialize_internal_event_with_non_null_ip() {
        // JSON with team_id and non-null IP (internal event with IP)
        let json_str = r#"{
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "distinct_id": "user123",
            "ip": "10.0.0.1",
            "data": "{\"event\": \"test\"}",
            "now": "2024-01-01T00:00:00Z",
            "sent_at": null,
            "token": "test_token",
            "is_cookieless_mode": false,
            "team_id": 456
        }"#;

        let event: CapturedEvent = serde_json::from_str(json_str).unwrap();

        // Should deserialize as Internal variant with IP
        assert!(matches!(event, CapturedEvent::Internal { .. }));
        assert_eq!(event.ip(), Some("10.0.0.1"));
        assert_eq!(event.team_id(), Some(456));
    }

    #[test]
    fn test_serialize_external_event() {
        let event = CapturedEvent::new_external(
            Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            "user123".to_string(),
            "192.168.1.1".to_string(),
            "{\"event\": \"test\"}".to_string(),
            "2024-01-01T00:00:00Z".to_string(),
            None,
            "test_token".to_string(),
            false,
        );

        let json = serde_json::to_value(&event).unwrap();

        // Verify serialized JSON has correct structure
        assert_eq!(json["uuid"], "550e8400-e29b-41d4-a716-446655440000");
        assert_eq!(json["distinct_id"], "user123");
        assert_eq!(json["ip"], "192.168.1.1");
        assert_eq!(json["token"], "test_token");
        assert!(json.get("team_id").is_none()); // Should not have team_id
    }

    #[test]
    fn test_serialize_internal_event_with_null_ip() {
        let event = CapturedEvent::new_internal(
            Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            "user123".to_string(),
            None,
            "{\"event\": \"test\"}".to_string(),
            "2024-01-01T00:00:00Z".to_string(),
            None,
            "test_token".to_string(),
            false,
            789,
        );

        let json = serde_json::to_value(&event).unwrap();

        // Verify serialized JSON has correct structure
        assert_eq!(json["uuid"], "550e8400-e29b-41d4-a716-446655440000");
        assert_eq!(json["distinct_id"], "user123");
        assert_eq!(json["ip"], json!(null));
        assert_eq!(json["token"], "test_token");
        assert_eq!(json["team_id"], 789);
    }

    #[test]
    fn test_serialize_internal_event_with_ip() {
        let event = CapturedEvent::new_internal(
            Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            "user123".to_string(),
            Some("10.0.0.1".to_string()),
            "{\"event\": \"test\"}".to_string(),
            "2024-01-01T00:00:00Z".to_string(),
            None,
            "test_token".to_string(),
            false,
            999,
        );

        let json = serde_json::to_value(&event).unwrap();

        // Verify serialized JSON has correct structure
        assert_eq!(json["uuid"], "550e8400-e29b-41d4-a716-446655440000");
        assert_eq!(json["distinct_id"], "user123");
        assert_eq!(json["ip"], "10.0.0.1");
        assert_eq!(json["token"], "test_token");
        assert_eq!(json["team_id"], 999);
    }

    #[test]
    fn test_roundtrip_external_event() {
        let original = CapturedEvent::new_external(
            Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            "user123".to_string(),
            "192.168.1.1".to_string(),
            "{\"event\": \"test\"}".to_string(),
            "2024-01-01T00:00:00Z".to_string(),
            None,
            "test_token".to_string(),
            true,
        );

        // Serialize and deserialize
        let json_str = serde_json::to_string(&original).unwrap();
        let deserialized: CapturedEvent = serde_json::from_str(&json_str).unwrap();

        // Verify all fields match
        assert_eq!(original, deserialized);
        assert_eq!(deserialized.ip(), Some("192.168.1.1"));
        assert_eq!(deserialized.team_id(), None);
        assert!(deserialized.is_cookieless_mode());
    }

    #[test]
    fn test_roundtrip_internal_event() {
        let original = CapturedEvent::new_internal(
            Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            "user123".to_string(),
            None,
            "{\"event\": \"test\"}".to_string(),
            "2024-01-01T00:00:00Z".to_string(),
            None,
            "test_token".to_string(),
            false,
            42,
        );

        // Serialize and deserialize
        let json_str = serde_json::to_string(&original).unwrap();
        let deserialized: CapturedEvent = serde_json::from_str(&json_str).unwrap();

        // Verify all fields match
        assert_eq!(original, deserialized);
        assert_eq!(deserialized.ip(), None);
        assert_eq!(deserialized.team_id(), Some(42));
    }

    #[test]
    fn test_backwards_compatibility_with_old_format() {
        // This tests that old code sending events without team_id still works
        let json_str = r#"{
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "distinct_id": "legacy_user",
            "ip": "1.2.3.4",
            "data": "{\"event\": \"legacy\"}",
            "now": "2024-01-01T00:00:00Z",
            "sent_at": null,
            "token": "legacy_token",
            "is_cookieless_mode": false
        }"#;

        let event: CapturedEvent = serde_json::from_str(json_str).unwrap();

        // Should work and be treated as external event
        assert!(matches!(event, CapturedEvent::External { .. }));
        assert_eq!(event.ip(), Some("1.2.3.4"));
        assert_eq!(event.team_id(), None);
    }

    #[test]
    fn test_plugin_server_format_with_null_ip() {
        // This simulates the exact format plugin-server sends
        let json_str = r#"{
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "distinct_id": "plugin_user",
            "ip": null,
            "data": "{\"event\": \"from_plugin\"}",
            "now": "2024-01-01T00:00:00Z",
            "sent_at": null,
            "token": "plugin_token",
            "is_cookieless_mode": false,
            "team_id": 100
        }"#;

        let event: CapturedEvent = serde_json::from_str(json_str).unwrap();

        // Should deserialize correctly as internal event
        assert!(matches!(event, CapturedEvent::Internal { .. }));
        assert_eq!(event.ip(), None);
        assert_eq!(event.team_id(), Some(100));
        assert_eq!(event.token(), "plugin_token");
        assert_eq!(event.distinct_id(), "plugin_user");

        // And should serialize back to same format
        let serialized = serde_json::to_value(&event).unwrap();
        assert_eq!(serialized["ip"], json!(null));
        assert_eq!(serialized["team_id"], 100);
    }

    #[test]
    fn test_deserialize_fails_without_required_ip_for_external() {
        // JSON without team_id and with null IP should fail
        let json_str = r#"{
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "distinct_id": "user123",
            "ip": null,
            "data": "{\"event\": \"test\"}",
            "now": "2024-01-01T00:00:00Z",
            "sent_at": null,
            "token": "test_token",
            "is_cookieless_mode": false
        }"#;

        let result: Result<CapturedEvent, _> = serde_json::from_str(json_str);

        // Should fail because external events require non-null IP
        assert!(result.is_err());
    }

    #[test]
    fn test_accessor_methods() {
        let external = CapturedEvent::new_external(
            Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            "user123".to_string(),
            "192.168.1.1".to_string(),
            "{\"event\": \"test\"}".to_string(),
            "2024-01-01T00:00:00Z".to_string(),
            None,
            "test_token".to_string(),
            false,
        );

        assert_eq!(
            external.uuid().to_string(),
            "550e8400-e29b-41d4-a716-446655440000"
        );
        assert_eq!(external.distinct_id(), "user123");
        assert_eq!(external.ip(), Some("192.168.1.1"));
        assert_eq!(external.data(), "{\"event\": \"test\"}");
        assert_eq!(external.now(), "2024-01-01T00:00:00Z");
        assert_eq!(external.sent_at(), None);
        assert_eq!(external.token(), "test_token");
        assert!(!external.is_cookieless_mode());
        assert!(external.team_id().is_none());
        assert!(!external.is_internal());

        let internal = CapturedEvent::new_internal(
            Uuid::parse_str("660e8400-e29b-41d4-a716-446655440000").unwrap(),
            "user456".to_string(),
            Some("10.0.0.1".to_string()),
            "{\"event\": \"internal\"}".to_string(),
            "2024-01-02T00:00:00Z".to_string(),
            None,
            "internal_token".to_string(),
            true,
            789,
        );

        assert_eq!(
            internal.uuid().to_string(),
            "660e8400-e29b-41d4-a716-446655440000"
        );
        assert_eq!(internal.distinct_id(), "user456");
        assert_eq!(internal.ip(), Some("10.0.0.1"));
        assert_eq!(internal.data(), "{\"event\": \"internal\"}");
        assert_eq!(internal.now(), "2024-01-02T00:00:00Z");
        assert_eq!(internal.sent_at(), None);
        assert_eq!(internal.token(), "internal_token");
        assert!(internal.is_cookieless_mode());
        assert_eq!(internal.team_id(), Some(789));
        assert!(internal.is_internal());
    }
}
