use anyhow::{anyhow, Result};
use common_types::RawEvent;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Bincode-compatible version of RawEvent that stores JSON as strings
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SerializableRawEvent {
    pub uuid: Option<String>,
    pub event: String,
    pub distinct_id_json: Option<String>, // JSON as string
    pub token: Option<String>,
    pub properties_json: String, // JSON as string
    pub timestamp: Option<String>,
    // Add other fields from RawEvent as needed, converting JSON fields to strings
}

impl From<&RawEvent> for SerializableRawEvent {
    fn from(raw_event: &RawEvent) -> Self {
        SerializableRawEvent {
            uuid: raw_event.uuid.map(|u| u.to_string()),
            event: raw_event.event.clone(),
            distinct_id_json: raw_event
                .distinct_id
                .as_ref()
                .map(|v| serde_json::to_string(v).unwrap_or_else(|_| "null".to_string())),
            token: raw_event.token.clone(),
            properties_json: serde_json::to_string(&raw_event.properties)
                .unwrap_or_else(|_| "{}".to_string()),
            timestamp: raw_event.timestamp.clone(),
        }
    }
}

impl TryFrom<&SerializableRawEvent> for RawEvent {
    type Error = anyhow::Error;

    fn try_from(serializable: &SerializableRawEvent) -> Result<Self> {
        let uuid = serializable
            .uuid
            .as_ref()
            .map(|s| s.parse().map_err(|e| anyhow!("Invalid UUID: {}", e)))
            .transpose()?;

        let distinct_id = serializable
            .distinct_id_json
            .as_ref()
            .map(|s| {
                serde_json::from_str(s).map_err(|e| anyhow!("Invalid distinct_id JSON: {}", e))
            })
            .transpose()?;

        let properties: HashMap<String, serde_json::Value> =
            serde_json::from_str(&serializable.properties_json)
                .map_err(|e| anyhow!("Invalid properties JSON: {}", e))?;

        Ok(RawEvent {
            uuid,
            event: serializable.event.clone(),
            distinct_id,
            token: serializable.token.clone(),
            properties,
            timestamp: serializable.timestamp.clone(),
            ..Default::default()
        })
    }
}

#[derive(Serialize, Deserialize, Debug)]
pub struct MetadataV1 {
    pub source: u8,
    pub team: u32,
    pub timestamp: u64,
    /// Original event data (serialized as JSON strings for bincode compatibility)
    pub original_event: SerializableRawEvent,
    /// Duplicate count for simple tracking
    pub duplicate_count: u64,
}

/// Trait that all metadata versions must implement
pub trait MetadataVersion {
    /// Update metrics when a duplicate is detected
    fn update_duplicate(&mut self, new_event: &RawEvent);
    /// Get a summary of the duplicate metrics for logging
    fn get_metrics_summary(&self) -> String;
}

/*
 * VersionedMetadata is a wrapper for the different versions of the metadata format.
 */
#[derive(Debug)]
pub enum VersionedMetadata {
    V1(MetadataV1),
}

impl VersionedMetadata {
    pub fn serialize_metadata(value: &Self) -> Result<Vec<u8>> {
        let mut buf = Vec::new();
        match value {
            VersionedMetadata::V1(v1) => {
                buf.push(1);
                let encoded = bincode::serde::encode_to_vec(v1, bincode::config::standard())?;
                buf.extend(encoded);
            }
        }
        Ok(buf)
    }

    pub fn deserialize_metadata(bytes: &[u8]) -> Result<VersionedMetadata> {
        let (version, payload) = bytes.split_first().ok_or_else(|| anyhow!("empty value"))?;
        match version {
            1 => {
                let (v1, _): (MetadataV1, _) =
                    bincode::serde::decode_from_slice(payload, bincode::config::standard())?;
                Ok(VersionedMetadata::V1(v1))
            }
            _ => Err(anyhow::anyhow!("unknown version: {}", version)),
        }
    }
}

impl MetadataVersion for VersionedMetadata {
    fn update_duplicate(&mut self, new_event: &RawEvent) {
        match self {
            VersionedMetadata::V1(v1) => v1.update_duplicate(new_event),
        }
    }

    fn get_metrics_summary(&self) -> String {
        match self {
            VersionedMetadata::V1(v1) => v1.get_metrics_summary(),
        }
    }
}

impl MetadataV1 {
    /// Create new metadata for the first occurrence of an event
    pub fn new(original_event: &RawEvent) -> Self {
        let timestamp = original_event
            .timestamp
            .as_ref()
            .and_then(|t| t.parse::<u64>().ok())
            .unwrap_or_else(|| chrono::Utc::now().timestamp() as u64);

        MetadataV1 {
            source: 1, // Default source, can be configured later
            team: 0,   // Default team, can be extracted from token if needed
            timestamp,
            original_event: SerializableRawEvent::from(original_event),
            duplicate_count: 0,
        }
    }

    /// Get the original RawEvent (deserializing from stored format)
    pub fn get_original_event(&self) -> Result<RawEvent> {
        RawEvent::try_from(&self.original_event)
    }
}

impl MetadataVersion for MetadataV1 {
    /// Update metrics when a duplicate is detected
    fn update_duplicate(&mut self, _new_event: &RawEvent) {
        self.duplicate_count += 1;
    }

    /// Get a summary of the duplicate metrics for logging
    fn get_metrics_summary(&self) -> String {
        format!("Duplicates: {}", self.duplicate_count)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_raw_event() -> RawEvent {
        // Keep properties empty to avoid bincode serialization issues with serde_json::Value
        let props = std::collections::HashMap::new();

        RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            properties: props,
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_metadata_v1_creation() {
        let raw_event = create_test_raw_event();

        let metadata = MetadataV1::new(&raw_event);

        assert_eq!(metadata.source, 1); // Default source
        assert_eq!(metadata.team, 0); // Default team
        assert_eq!(metadata.timestamp, 1234567890);
        assert_eq!(metadata.duplicate_count, 0);
    }

    #[test]
    fn test_metadata_v1_serialization() {
        let raw_event = create_test_raw_event();
        let metadata = MetadataV1::new(&raw_event);
        let versioned = VersionedMetadata::V1(metadata);

        // Test full serialization/deserialization round-trip
        let serialized = VersionedMetadata::serialize_metadata(&versioned).unwrap();
        let deserialized = VersionedMetadata::deserialize_metadata(&serialized).unwrap();

        // Check that version byte is present
        assert_eq!(serialized[0], 1);
        assert!(serialized.len() > 1);

        // Verify deserialized data matches original
        match deserialized {
            VersionedMetadata::V1(v1) => {
                assert_eq!(v1.source, 1);
                assert_eq!(v1.team, 0);
                assert_eq!(v1.timestamp, 1234567890);
                assert_eq!(v1.duplicate_count, 0);
            }
        }
    }

    #[test]
    fn test_metadata_v1_trait_methods() {
        let raw_event = create_test_raw_event();
        let mut metadata = MetadataV1::new(&raw_event);

        // Test initial state
        let summary = metadata.get_metrics_summary();
        assert!(summary.contains("Duplicates: 0"));

        // Test update_duplicate method
        let duplicate_event = create_test_raw_event();
        metadata.update_duplicate(&duplicate_event);

        // Verify metrics were updated
        let updated_summary = metadata.get_metrics_summary();
        assert!(updated_summary.contains("Duplicates: 1"));
    }

    #[test]
    fn test_update_duplicate() {
        let original_raw = create_test_raw_event();
        let mut metadata = MetadataV1::new(&original_raw);

        // Create a duplicate with different UUID
        let duplicate_raw = create_test_raw_event();
        metadata.update_duplicate(&duplicate_raw);

        assert_eq!(metadata.duplicate_count, 1);
    }

    #[test]
    fn test_serialization_with_properties() {
        // Test with RawEvent that has properties (like in real usage)
        let mut props = std::collections::HashMap::new();
        props.insert("url".to_string(), serde_json::json!("/home"));
        props.insert("referrer".to_string(), serde_json::json!("google"));
        props.insert("count".to_string(), serde_json::json!(42));
        props.insert("active".to_string(), serde_json::json!(true));

        let raw_event = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token456".to_string()),
            properties: props,
            timestamp: Some("1640995200".to_string()),
            ..Default::default()
        };

        let metadata = MetadataV1::new(&raw_event);
        let versioned = VersionedMetadata::V1(metadata);

        // This should catch the bincode 2.x serialization issue
        let serialized_result = VersionedMetadata::serialize_metadata(&versioned);
        match serialized_result {
            Ok(serialized) => {
                // If serialization works, test deserialization too
                let deserialized = VersionedMetadata::deserialize_metadata(&serialized).unwrap();
                match deserialized {
                    VersionedMetadata::V1(v1) => {
                        assert_eq!(v1.duplicate_count, 0);
                        assert_eq!(v1.original_event.event, "page_view");

                        // Verify the properties were serialized correctly
                        let properties: HashMap<String, serde_json::Value> =
                            serde_json::from_str(&v1.original_event.properties_json).unwrap();
                        assert_eq!(properties.len(), 4);
                        assert_eq!(properties["url"], serde_json::json!("/home"));
                        assert_eq!(properties["referrer"], serde_json::json!("google"));
                    }
                }
            }
            Err(e) => {
                // If serialization fails, the test should fail with clear error message
                panic!("Serialization failed with properties: {e}");
            }
        }
    }

    #[test]
    fn test_deserialize_invalid_version() {
        let invalid_data = vec![99, 1, 2, 3]; // version 99 doesn't exist
        let result = VersionedMetadata::deserialize_metadata(&invalid_data);

        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("unknown version: 99"));
    }

    #[test]
    fn test_deserialize_empty_data() {
        let empty_data = vec![];
        let result = VersionedMetadata::deserialize_metadata(&empty_data);

        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("empty value"));
    }

    #[test]
    fn test_deserialize_corrupted_payload() {
        let corrupted_data = vec![1, 255, 255, 255]; // version 1 but invalid bincode
        let result = VersionedMetadata::deserialize_metadata(&corrupted_data);

        assert!(result.is_err());
    }
}
