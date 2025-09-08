use anyhow::{Context, Result};
use common_types::RawEvent;

use crate::utils::timestamp::parse_timestamp;

const UNKNOWN_STR: &str = "unknown";

/// Timestamp-based deduplication key
/// Format: timestamp:distinct_id:token:event_name
#[derive(Debug, Clone, Hash, PartialEq, Eq)]
pub struct TimestampKey {
    pub timestamp: u64,
    pub distinct_id: String,
    pub token: String,
    pub event_name: String,
    formatted_key: String,
}

impl TimestampKey {
    pub fn new(timestamp: u64, distinct_id: String, token: String, event_name: String) -> Self {
        let formatted_key = format!("{timestamp}:{distinct_id}:{token}:{event_name}");
        Self {
            timestamp,
            distinct_id,
            token,
            event_name,
            formatted_key,
        }
    }

    pub fn get_formatted_key(&self) -> &str {
        &self.formatted_key
    }
}

impl AsRef<[u8]> for TimestampKey {
    fn as_ref(&self) -> &[u8] {
        self.formatted_key.as_bytes()
    }
}

impl From<TimestampKey> for Vec<u8> {
    fn from(key: TimestampKey) -> Vec<u8> {
        key.formatted_key.as_bytes().to_vec()
    }
}

impl From<&TimestampKey> for Vec<u8> {
    fn from(key: &TimestampKey) -> Vec<u8> {
        key.formatted_key.as_bytes().to_vec()
    }
}

impl TryFrom<&[u8]> for TimestampKey {
    type Error = anyhow::Error;

    fn try_from(bytes: &[u8]) -> Result<Self> {
        let key_str = std::str::from_utf8(bytes)
            .with_context(|| format!("Invalid UTF-8 in timestamp key: {bytes:?}"))?;
        let parts: Vec<&str> = key_str.split(':').collect();

        if parts.len() != 4 {
            return Err(anyhow::anyhow!(
                "Invalid timestamp key format '{}', expected 4 parts separated by ':' (timestamp:distinct_id:token:event_name)",
                key_str
            ));
        }

        Ok(Self::new(
            parts[0].parse::<u64>().with_context(|| {
                format!("Failed to parse timestamp '{}' in timestamp key", parts[0])
            })?,
            parts[1].to_string(),
            parts[2].to_string(),
            parts[3].to_string(),
        ))
    }
}

impl From<&RawEvent> for TimestampKey {
    fn from(raw_event: &RawEvent) -> Self {
        let timestamp = raw_event
            .timestamp
            .as_ref()
            .and_then(|t| parse_timestamp(t))
            .unwrap_or_else(|| chrono::Utc::now().timestamp_millis() as u64);

        let distinct_id = extract_distinct_id(raw_event);
        let token = raw_event
            .token
            .clone()
            .unwrap_or_else(|| UNKNOWN_STR.to_string());

        Self::new(timestamp, distinct_id, token, raw_event.event.clone())
    }
}

/// UUID-based deduplication key
/// Format: uuid:distinct_id:token:event_name
#[derive(Debug, Clone, Hash, PartialEq, Eq)]
pub struct UuidKey {
    pub uuid: String,
    pub distinct_id: String,
    pub token: String,
    pub event_name: String,
    formatted_key: String,
}

impl UuidKey {
    pub fn new(uuid: String, distinct_id: String, token: String, event_name: String) -> Self {
        let formatted_key = format!("{uuid}:{distinct_id}:{token}:{event_name}");
        Self {
            uuid,
            distinct_id,
            token,
            event_name,
            formatted_key,
        }
    }

    pub fn get_formatted_key(&self) -> &str {
        &self.formatted_key
    }
}

impl AsRef<[u8]> for UuidKey {
    fn as_ref(&self) -> &[u8] {
        self.formatted_key.as_bytes()
    }
}

impl From<UuidKey> for Vec<u8> {
    fn from(key: UuidKey) -> Vec<u8> {
        key.formatted_key.as_bytes().to_vec()
    }
}

impl From<&UuidKey> for Vec<u8> {
    fn from(key: &UuidKey) -> Vec<u8> {
        key.formatted_key.as_bytes().to_vec()
    }
}

impl TryFrom<&[u8]> for UuidKey {
    type Error = anyhow::Error;

    fn try_from(bytes: &[u8]) -> Result<Self> {
        let key_str = std::str::from_utf8(bytes)
            .with_context(|| format!("Invalid UTF-8 in UUID key: {bytes:?}"))?;
        let parts: Vec<&str> = key_str.split(':').collect();

        if parts.len() != 4 {
            return Err(anyhow::anyhow!(
                "Invalid UUID key format '{}', expected 4 parts separated by ':' (uuid:distinct_id:token:event_name)",
                key_str
            ));
        }

        Ok(Self::new(
            parts[0].to_string(),
            parts[1].to_string(),
            parts[2].to_string(),
            parts[3].to_string(),
        ))
    }
}

impl From<&RawEvent> for UuidKey {
    fn from(raw_event: &RawEvent) -> Self {
        let uuid = raw_event
            .uuid
            .map(|u| u.to_string())
            .unwrap_or_else(|| UNKNOWN_STR.to_string());

        let distinct_id = extract_distinct_id(raw_event);
        let token = raw_event
            .token
            .clone()
            .unwrap_or_else(|| UNKNOWN_STR.to_string());

        Self::new(uuid, distinct_id, token, raw_event.event.clone())
    }
}

/// Helper function to extract distinct_id from RawEvent
fn extract_distinct_id(raw_event: &RawEvent) -> String {
    raw_event
        .distinct_id
        .as_ref()
        .and_then(|v| {
            // Treat JSON null as None
            if v.is_null() {
                None
            } else {
                // Try to get as string first, if not possible stringify the JSON
                Some(
                    v.as_str()
                        .map(|s| s.to_string())
                        .unwrap_or_else(|| v.to_string()),
                )
            }
        })
        .unwrap_or_else(|| UNKNOWN_STR.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_event() -> RawEvent {
        RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token456".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_timestamp_key_formatting() {
        let event = create_test_event();
        let key = TimestampKey::from(&event);

        // Parse the ISO timestamp to get the milliseconds value
        let timestamp_millis = parse_timestamp(event.timestamp.as_ref().unwrap()).unwrap();

        let expected = format!("{timestamp_millis}:user123:token456:test_event");
        assert_eq!(String::from_utf8_lossy(key.as_ref()), expected);
    }

    #[test]
    fn test_uuid_key_formatting() {
        let event = create_test_event();
        let key = UuidKey::from(&event);

        let uuid_str = event.uuid.unwrap().to_string();
        let expected = format!("{uuid_str}:user123:token456:test_event");
        assert_eq!(String::from_utf8_lossy(key.as_ref()), expected);
    }

    #[test]
    fn test_timestamp_key_roundtrip() {
        let event = create_test_event();
        let key = TimestampKey::from(&event);

        let key_bytes: Vec<u8> = (&key).into();
        let parsed_key = TimestampKey::try_from(key_bytes.as_slice()).unwrap();

        assert_eq!(key.timestamp, parsed_key.timestamp);
        assert_eq!(key.distinct_id, parsed_key.distinct_id);
        assert_eq!(key.token, parsed_key.token);
        assert_eq!(key.event_name, parsed_key.event_name);
    }

    #[test]
    fn test_uuid_key_roundtrip() {
        let event = create_test_event();
        let key = UuidKey::from(&event);

        let key_bytes: Vec<u8> = (&key).into();
        let parsed_key = UuidKey::try_from(key_bytes.as_slice()).unwrap();

        assert_eq!(key.uuid, parsed_key.uuid);
        assert_eq!(key.distinct_id, parsed_key.distinct_id);
        assert_eq!(key.token, parsed_key.token);
        assert_eq!(key.event_name, parsed_key.event_name);
    }
}
