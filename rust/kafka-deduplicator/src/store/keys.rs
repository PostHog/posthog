use anyhow::{Context, Result};
use common_types::RawEvent;
use serde::{Deserialize, Serialize};

use crate::utils::timestamp::parse_timestamp;

const UNKNOWN_STR: &str = "unknown";

/// Timestamp-based deduplication key
/// Uses bincode serialization to handle arbitrary characters in fields
#[derive(Debug, Clone, Hash, PartialEq, Eq, Serialize, Deserialize)]
pub struct TimestampKey {
    pub timestamp: u64,
    pub distinct_id: String,
    pub token: String,
    pub event_name: String,
}

impl TimestampKey {
    pub fn new(timestamp: u64, distinct_id: String, token: String, event_name: String) -> Self {
        Self {
            timestamp,
            distinct_id,
            token,
            event_name,
        }
    }
}

impl From<TimestampKey> for Vec<u8> {
    fn from(key: TimestampKey) -> Vec<u8> {
        // Custom serialization to ensure timestamp comes first for proper ordering
        // Format: [8 bytes timestamp BE][rest as bincode]
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&key.timestamp.to_be_bytes());

        // Serialize the rest of the fields
        let rest = (key.distinct_id, key.token, key.event_name);
        let rest_bytes = bincode::serde::encode_to_vec(&rest, bincode::config::standard())
            .expect("TimestampKey serialization should never fail");
        bytes.extend_from_slice(&rest_bytes);
        bytes
    }
}

impl From<&TimestampKey> for Vec<u8> {
    fn from(key: &TimestampKey) -> Vec<u8> {
        // Custom serialization to ensure timestamp comes first for proper ordering
        // Format: [8 bytes timestamp BE][rest as bincode]
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&key.timestamp.to_be_bytes());

        // Serialize the rest of the fields
        let rest = (&key.distinct_id, &key.token, &key.event_name);
        let rest_bytes = bincode::serde::encode_to_vec(rest, bincode::config::standard())
            .expect("TimestampKey serialization should never fail");
        bytes.extend_from_slice(&rest_bytes);
        bytes
    }
}

impl TryFrom<&[u8]> for TimestampKey {
    type Error = anyhow::Error;

    fn try_from(bytes: &[u8]) -> Result<Self> {
        // Custom deserialization to match our serialization format
        // Format: [8 bytes timestamp BE][rest as bincode]
        if bytes.len() < 8 {
            anyhow::bail!("TimestampKey bytes too short: {} bytes", bytes.len());
        }

        // Extract timestamp
        let timestamp_bytes: [u8; 8] = bytes[..8].try_into()?;
        let timestamp = u64::from_be_bytes(timestamp_bytes);

        // Deserialize the rest
        let (rest, _): ((String, String, String), usize) =
            bincode::serde::decode_from_slice(&bytes[8..], bincode::config::standard())
                .with_context(|| {
                    format!(
                        "Failed to deserialize TimestampKey fields from {} bytes",
                        bytes.len() - 8
                    )
                })?;

        Ok(TimestampKey {
            timestamp,
            distinct_id: rest.0,
            token: rest.1,
            event_name: rest.2,
        })
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
/// Uses bincode serialization to handle arbitrary characters in fields
#[derive(Debug, Clone, Hash, PartialEq, Eq, Serialize, Deserialize)]
pub struct UuidKey {
    pub uuid: String,
    pub distinct_id: String,
    pub token: String,
    pub event_name: String,
}

impl UuidKey {
    pub fn new(uuid: String, distinct_id: String, token: String, event_name: String) -> Self {
        Self {
            uuid,
            distinct_id,
            token,
            event_name,
        }
    }
}

impl From<UuidKey> for Vec<u8> {
    fn from(key: UuidKey) -> Vec<u8> {
        bincode::serde::encode_to_vec(&key, bincode::config::standard())
            .expect("UuidKey serialization should never fail")
    }
}

impl From<&UuidKey> for Vec<u8> {
    fn from(key: &UuidKey) -> Vec<u8> {
        bincode::serde::encode_to_vec(key, bincode::config::standard())
            .expect("UuidKey serialization should never fail")
    }
}

impl TryFrom<&[u8]> for UuidKey {
    type Error = anyhow::Error;

    fn try_from(bytes: &[u8]) -> Result<Self> {
        let (key, _): (UuidKey, usize) =
            bincode::serde::decode_from_slice(bytes, bincode::config::standard()).with_context(
                || format!("Failed to deserialize UuidKey from {} bytes", bytes.len()),
            )?;
        Ok(key)
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

/// Index key for UUID records, prefixed with timestamp for efficient cleanup
#[derive(Debug, Clone)]
pub struct UuidIndexKey {
    timestamp: u64,
    uuid_key: Vec<u8>,
}

impl UuidIndexKey {
    pub fn new(timestamp: u64, uuid_key: Vec<u8>) -> Self {
        Self {
            timestamp,
            uuid_key,
        }
    }

    /// Create index key from timestamp and UuidKey
    pub fn from_uuid_key(timestamp: u64, uuid_key: &UuidKey) -> Self {
        Self {
            timestamp,
            uuid_key: uuid_key.into(),
        }
    }

    /// Parse timestamp from an index key bytes
    pub fn parse_timestamp(bytes: &[u8]) -> Option<u64> {
        if bytes.len() >= 8 {
            let timestamp_bytes: [u8; 8] = bytes[..8].try_into().ok()?;
            Some(u64::from_be_bytes(timestamp_bytes))
        } else {
            None
        }
    }

    /// Create a range start key for deletion (inclusive)
    pub fn range_start() -> Vec<u8> {
        0u64.to_be_bytes().to_vec()
    }

    /// Create a range end key for deletion (exclusive)
    /// We add 0xFF bytes to ensure this key comes after all keys with the cleanup timestamp
    pub fn range_end(cleanup_timestamp: u64) -> Vec<u8> {
        let mut bytes = cleanup_timestamp.to_be_bytes().to_vec();
        // Add a suffix to ensure this key is greater than any key with this timestamp
        bytes.push(0xFF);
        bytes
    }
}

impl From<UuidIndexKey> for Vec<u8> {
    fn from(key: UuidIndexKey) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(8 + key.uuid_key.len());
        bytes.extend_from_slice(&key.timestamp.to_be_bytes());
        bytes.extend_from_slice(&key.uuid_key);
        bytes
    }
}

impl From<&UuidIndexKey> for Vec<u8> {
    fn from(key: &UuidIndexKey) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(8 + key.uuid_key.len());
        bytes.extend_from_slice(&key.timestamp.to_be_bytes());
        bytes.extend_from_slice(&key.uuid_key);
        bytes
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
    fn test_timestamp_key_serialization() {
        let event = create_test_event();
        let key = TimestampKey::from(&event);

        // Test that we can serialize and deserialize
        let serialized: Vec<u8> = (&key).into();
        let deserialized = TimestampKey::try_from(serialized.as_slice()).unwrap();

        assert_eq!(key, deserialized);
        assert_eq!(deserialized.distinct_id, "user123");
        assert_eq!(deserialized.token, "token456");
        assert_eq!(deserialized.event_name, "test_event");
    }

    #[test]
    fn test_uuid_key_serialization() {
        let event = create_test_event();
        let key = UuidKey::from(&event);

        // Test that we can serialize and deserialize
        let serialized: Vec<u8> = (&key).into();
        let deserialized = UuidKey::try_from(serialized.as_slice()).unwrap();

        assert_eq!(key, deserialized);
        assert_eq!(deserialized.distinct_id, "user123");
        assert_eq!(deserialized.token, "token456");
        assert_eq!(deserialized.event_name, "test_event");
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
