use anyhow::{anyhow, Result};
use common_types::RawEvent;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use uuid::Uuid;

use crate::utils::timestamp::parse_timestamp;

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
    /// Set of UUIDs that have been seen for this dedupe key
    pub seen_uuids: HashSet<String>,
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
            .unwrap_or_else(|| chrono::Utc::now().timestamp_millis() as u64);

        let mut seen_uuids = HashSet::new();
        if let Some(uuid) = original_event.uuid {
            seen_uuids.insert(uuid.to_string());
        }

        MetadataV1 {
            source: 1, // Default source, can be configured later
            team: 0,   // Default team, can be extracted from token if needed
            timestamp,
            original_event: SerializableRawEvent::from(original_event),
            duplicate_count: 0,
            seen_uuids,
        }
    }

    /// Get the original RawEvent (deserializing from stored format)
    pub fn get_original_event(&self) -> Result<RawEvent> {
        RawEvent::try_from(&self.original_event)
    }

    /// Calculate similarity between two events
    pub fn calculate_similarity(&self, new_event: &RawEvent) -> Result<EventSimilarity> {
        let original_event = self.get_original_event()?;
        EventSimilarity::calculate(&original_event, new_event)
    }
}

/// Type alias for property differences
type PropertyDifference = (String, Option<(String, String)>);

/// Field names used in deduplication comparisons
#[derive(Debug, Clone, PartialEq, strum_macros::Display, strum_macros::EnumString)]
#[strum(serialize_all = "snake_case")]
pub enum DedupFieldName {
    Event,
    DistinctId,
    Token,
    Timestamp,
    Set,
    SetOnce,
    Uuid,
    Properties,
}

/// Represents the similarity between two events
#[derive(Debug)]
pub struct EventSimilarity {
    /// Total similarity score (0.0 = completely different, 1.0 = identical)
    pub overall_score: f64,
    /// Number of top-level fields that differ (excluding properties)
    pub different_field_count: u32,
    /// List of field names that differ with their values (original -> new)
    pub different_fields: Vec<(DedupFieldName, String, String)>, // (field_name, original_value, new_value)
    /// Properties similarity score (0.0 = completely different, 1.0 = identical)
    pub properties_similarity: f64,
    /// Number of properties that differ
    pub different_property_count: u32,
    /// List of properties that differ with values for $ properties, just key names for others
    /// Format: (property_name, Option<(original_value, new_value)>)
    pub different_properties: Vec<PropertyDifference>,
}

impl std::fmt::Display for EventSimilarity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:.2}", self.overall_score)
    }
}

impl EventSimilarity {
    pub fn calculate(original: &RawEvent, new: &RawEvent) -> Result<Self> {
        let mut different_fields = Vec::new();
        let mut matching_fields = 0u32;
        let mut total_fields = 0u32;

        // Helper to format optional values for display
        let format_opt = |opt: &Option<String>| opt.as_deref().unwrap_or("<none>").to_string();
        let format_value_opt = |opt: &Option<serde_json::Value>| {
            opt.as_ref()
                .map(|v| v.to_string())
                .unwrap_or_else(|| "<none>".to_string())
        };
        let format_map_opt = |opt: &Option<HashMap<String, serde_json::Value>>| {
            opt.as_ref()
                .map(|m| format!("{} properties", m.len()))
                .unwrap_or_else(|| "<none>".to_string())
        };

        // Compare top-level fields (including uuid for proper OnlyUuidDifferent detection)
        total_fields += 1;
        if original.event == new.event {
            matching_fields += 1;
        } else {
            different_fields.push((
                DedupFieldName::Event,
                original.event.clone(),
                new.event.clone(),
            ));
        }

        total_fields += 1;
        if original.distinct_id == new.distinct_id {
            matching_fields += 1;
        } else {
            different_fields.push((
                DedupFieldName::DistinctId,
                format_value_opt(&original.distinct_id),
                format_value_opt(&new.distinct_id),
            ));
        }

        total_fields += 1;
        if original.token == new.token {
            matching_fields += 1;
        } else {
            different_fields.push((
                DedupFieldName::Token,
                format_opt(&original.token),
                format_opt(&new.token),
            ));
        }

        // Compare timestamps - check if they parse to the same u64 value
        // Use parse_timestamp which handles both numeric and ISO formats
        total_fields += 1;
        let original_ts = original.timestamp.as_ref().and_then(|t| parse_timestamp(t));
        let new_ts = new.timestamp.as_ref().and_then(|t| parse_timestamp(t));

        if original_ts == new_ts {
            matching_fields += 1;
        } else {
            different_fields.push((
                DedupFieldName::Timestamp,
                original_ts
                    .map(|ts| ts.to_string())
                    .unwrap_or_else(|| "<invalid>".to_string()),
                new_ts
                    .map(|ts| ts.to_string())
                    .unwrap_or_else(|| "<invalid>".to_string()),
            ));
        }

        total_fields += 1;
        if original.set == new.set {
            matching_fields += 1;
        } else {
            different_fields.push((
                DedupFieldName::Set,
                format_map_opt(&original.set),
                format_map_opt(&new.set),
            ));
        }

        total_fields += 1;
        if original.set_once == new.set_once {
            matching_fields += 1;
        } else {
            different_fields.push((
                DedupFieldName::SetOnce,
                format_map_opt(&original.set_once),
                format_map_opt(&new.set_once),
            ));
        }

        // Compare UUID
        total_fields += 1;
        if original.uuid == new.uuid {
            matching_fields += 1;
        } else {
            let format_uuid = |opt: &Option<Uuid>| {
                opt.map(|u| u.to_string())
                    .unwrap_or_else(|| "<none>".to_string())
            };
            different_fields.push((
                DedupFieldName::Uuid,
                format_uuid(&original.uuid),
                format_uuid(&new.uuid),
            ));
        }

        // Compare properties
        let (properties_similarity, different_properties) =
            Self::compare_properties(&original.properties, &new.properties);

        // If properties differ, add them to different_fields
        if !different_properties.is_empty() {
            let orig_summary = format!("{} properties", original.properties.len());
            let new_summary = format!("{} properties", new.properties.len());
            different_fields.push((DedupFieldName::Properties, orig_summary, new_summary));
        }

        let different_field_count = different_fields.len() as u32;
        let different_property_count = different_properties.len() as u32;

        // Calculate overall similarity score
        // Weight: 70% field similarity, 30% properties similarity
        let field_similarity = if total_fields > 0 {
            matching_fields as f64 / total_fields as f64
        } else {
            1.0
        };

        let overall_score = field_similarity * 0.7 + properties_similarity * 0.3;

        Ok(EventSimilarity {
            overall_score,
            different_field_count,
            different_fields,
            properties_similarity,
            different_property_count,
            different_properties,
        })
    }

    fn compare_properties(
        original: &HashMap<String, serde_json::Value>,
        new: &HashMap<String, serde_json::Value>,
    ) -> (f64, Vec<PropertyDifference>) {
        let mut different_properties = Vec::new();

        // Get all unique keys from both maps
        let all_keys: HashSet<&String> = original.keys().chain(new.keys()).collect();

        if all_keys.is_empty() {
            return (1.0, different_properties);
        }

        let mut matching = 0;
        for key in &all_keys {
            let original_val = original.get(*key);
            let new_val = new.get(*key);

            match (original_val, new_val) {
                (Some(v1), Some(v2)) if v1 == v2 => matching += 1,
                (original_opt, new_opt) => {
                    // For $ properties (PostHog system properties), include values
                    // For other properties, just record the key for privacy
                    let values = if key.starts_with('$') {
                        let orig_str = original_opt
                            .map(|v| v.to_string())
                            .unwrap_or_else(|| "<not set>".to_string());
                        let new_str = new_opt
                            .map(|v| v.to_string())
                            .unwrap_or_else(|| "<not set>".to_string());
                        Some((orig_str, new_str))
                    } else {
                        None
                    };

                    different_properties.push(((*key).to_string(), values));
                }
            }
        }

        let similarity = matching as f64 / all_keys.len() as f64;
        (similarity, different_properties)
    }
}

impl MetadataVersion for MetadataV1 {
    /// Update metrics when a duplicate is detected
    fn update_duplicate(&mut self, new_event: &RawEvent) {
        self.duplicate_count += 1;

        // Track UUID if present
        if let Some(uuid) = new_event.uuid {
            self.seen_uuids.insert(uuid.to_string());
        }
    }

    /// Get a summary of the duplicate metrics for logging
    fn get_metrics_summary(&self) -> String {
        format!(
            "Duplicates: {}, Unique UUIDs: {}",
            self.duplicate_count,
            self.seen_uuids.len()
        )
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
        assert_eq!(metadata.seen_uuids.len(), 1); // Should contain the initial UUID
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
        assert!(summary.contains("Unique UUIDs: 1"));

        // Test update_duplicate method
        let duplicate_event = create_test_raw_event();
        metadata.update_duplicate(&duplicate_event);

        // Verify metrics were updated
        let updated_summary = metadata.get_metrics_summary();
        assert!(updated_summary.contains("Duplicates: 1"));
        assert!(updated_summary.contains("Unique UUIDs: 2")); // Two different UUIDs now
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

    #[test]
    fn test_event_similarity_calculation() {
        // Create two events with some differences
        let event1 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token123".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("url".to_string(), serde_json::json!("/home"));
                props.insert("referrer".to_string(), serde_json::json!("google"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()), // Different UUID (expected)
            event: "page_view".to_string(),   // Same event
            distinct_id: Some(serde_json::Value::String("user123".to_string())), // Same distinct_id
            token: Some("token123".to_string()), // Same token
            properties: {
                let mut props = HashMap::new();
                props.insert("url".to_string(), serde_json::json!("/about")); // Different URL
                props.insert("referrer".to_string(), serde_json::json!("google")); // Same referrer
                props.insert("browser".to_string(), serde_json::json!("chrome")); // New property
                props
            },
            timestamp: Some("1234567891".to_string()), // Different timestamp
            ..Default::default()
        };

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        assert_eq!(similarity.different_field_count, 3); // UUID, timestamp, and properties differ
        assert!(similarity
            .different_fields
            .iter()
            .any(|(field, _, _)| field == &DedupFieldName::Timestamp));
        assert!(similarity
            .different_fields
            .iter()
            .any(|(field, _, _)| field == &DedupFieldName::Uuid));
        assert!(similarity
            .different_fields
            .iter()
            .any(|(field, _, _)| field == &DedupFieldName::Properties));

        assert_eq!(similarity.different_property_count, 2); // url differs, browser is new
        assert!(similarity
            .different_properties
            .iter()
            .any(|(prop, _)| prop == "url"));
        assert!(similarity
            .different_properties
            .iter()
            .any(|(prop, _)| prop == "browser"));

        assert!(similarity.properties_similarity > 0.0 && similarity.properties_similarity < 1.0);
        assert!(similarity.overall_score > 0.0 && similarity.overall_score < 1.0);
    }

    #[test]
    fn test_event_similarity_identical() {
        let uuid = uuid::Uuid::new_v4();
        let event1 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token123".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("key".to_string(), serde_json::json!("value"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token123".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("key".to_string(), serde_json::json!("value"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        assert_eq!(similarity.different_field_count, 0);
        assert_eq!(similarity.different_property_count, 0);
        assert_eq!(similarity.properties_similarity, 1.0);
        assert_eq!(similarity.overall_score, 1.0);
    }

    #[test]
    fn test_uuid_tracking() {
        let uuid1 = uuid::Uuid::new_v4();
        let uuid2 = uuid::Uuid::new_v4();
        let uuid3 = uuid::Uuid::new_v4();

        let event1 = RawEvent {
            uuid: Some(uuid1),
            event: "test".to_string(),
            ..Default::default()
        };

        let mut metadata = MetadataV1::new(&event1);
        assert_eq!(metadata.seen_uuids.len(), 1);
        assert!(metadata.seen_uuids.contains(&uuid1.to_string()));

        // Add duplicate with different UUID
        let event2 = RawEvent {
            uuid: Some(uuid2),
            event: "test".to_string(),
            ..Default::default()
        };
        metadata.update_duplicate(&event2);
        assert_eq!(metadata.seen_uuids.len(), 2);
        assert!(metadata.seen_uuids.contains(&uuid2.to_string()));

        let event3 = RawEvent {
            uuid: Some(uuid1),
            event: "test".to_string(),
            ..Default::default()
        };
        metadata.update_duplicate(&event3);
        assert_eq!(metadata.seen_uuids.len(), 2); // Should still be 2, not 3

        let event4 = RawEvent {
            uuid: Some(uuid3),
            event: "test".to_string(),
            ..Default::default()
        };
        metadata.update_duplicate(&event4);
        assert_eq!(metadata.seen_uuids.len(), 3);
    }

    #[test]
    fn test_complete_duplicate_tracking_with_similarity() {
        // Create an original event with rich properties
        let uuid1 = uuid::Uuid::new_v4();
        let original_event = RawEvent {
            uuid: Some(uuid1),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::json!("user123")),
            token: Some("project_token".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("url".to_string(), serde_json::json!("/home"));
                props.insert("browser".to_string(), serde_json::json!("chrome"));
                props.insert("referrer".to_string(), serde_json::json!("google"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        // Create metadata
        let mut metadata = MetadataV1::new(&original_event);

        // First duplicate - different UUID, slightly different properties
        let uuid2 = uuid::Uuid::new_v4();
        let duplicate1 = RawEvent {
            uuid: Some(uuid2),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::json!("user123")),
            token: Some("project_token".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("url".to_string(), serde_json::json!("/home"));
                props.insert("browser".to_string(), serde_json::json!("firefox")); // Different
                props.insert("referrer".to_string(), serde_json::json!("google"));
                props.insert("session_id".to_string(), serde_json::json!("abc123")); // New field
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let similarity1 = metadata.calculate_similarity(&duplicate1).unwrap();
        metadata.update_duplicate(&duplicate1);

        // Verify similarity metrics
        assert_eq!(similarity1.different_field_count, 2); // UUID and properties differ
        assert_eq!(similarity1.different_property_count, 2); // browser differs, session_id is new
        assert!(similarity1.properties_similarity < 1.0);
        assert!(similarity1.properties_similarity > 0.0);

        // Second duplicate - same UUID as original, different properties
        let duplicate2 = RawEvent {
            uuid: Some(uuid1), // Same UUID as original
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::json!("user123")),
            token: Some("project_token".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("url".to_string(), serde_json::json!("/about")); // Different URL
                props.insert("browser".to_string(), serde_json::json!("chrome"));
                props.insert("referrer".to_string(), serde_json::json!("bing")); // Different referrer
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let similarity2 = metadata.calculate_similarity(&duplicate2).unwrap();
        metadata.update_duplicate(&duplicate2);

        // Properties are quite different
        assert!(similarity2.different_property_count >= 2);

        // Check final state
        assert_eq!(metadata.duplicate_count, 2);
        assert_eq!(metadata.seen_uuids.len(), 2); // Only 2 unique UUIDs
        let summary = metadata.get_metrics_summary();
        assert!(summary.contains("Duplicates: 2"));
        assert!(summary.contains("Unique UUIDs: 2"));
    }

    #[test]
    fn test_non_ascii_timestamp_handling() {
        // Test that non-ASCII timestamps don't cause panics when calculating similarity
        let event1 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::json!("user123")),
            token: Some("token1".to_string()),
            // Czech timestamp with non-ASCII characters that previously caused panics
            timestamp: Some("2025-09-02T14:45:58.462 září 12:46:52 +00:00".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::json!("user123")),
            token: Some("token1".to_string()),
            timestamp: Some("2025-09-02T14:45:58.462Z".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        };

        // This should not panic even with non-ASCII timestamp
        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        // Timestamps are different (one invalid, one valid), so they should show as different
        assert!(similarity
            .different_fields
            .iter()
            .any(|(field, _, _)| field == &DedupFieldName::Timestamp));

        // First timestamp is invalid (has non-ASCII), second is valid ISO
        let timestamp_diff = similarity
            .different_fields
            .iter()
            .find(|(field, _, _)| field == &DedupFieldName::Timestamp)
            .unwrap();
        assert_eq!(timestamp_diff.1, "<invalid>"); // Czech timestamp can't be parsed
                                                   // Second timestamp is valid ISO format, should show the milliseconds value
        assert!(timestamp_diff.2 != "<invalid>");
    }

    #[test]
    fn test_completely_different_events_similarity() {
        let event1 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::json!("user123")),
            token: Some("token_a".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("key1".to_string(), serde_json::json!("value1"));
                props
            },
            timestamp: Some("1111111111".to_string()),
            offset: Some(100),
            set: Some(HashMap::new()),
            set_once: None,
        };

        let event2 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "button_click".to_string(), // Different
            distinct_id: Some(serde_json::json!("user456")), // Different
            token: Some("token_b".to_string()), // Different
            properties: {
                let mut props = HashMap::new();
                props.insert("key2".to_string(), serde_json::json!("value2")); // Completely different
                props
            },
            timestamp: Some("2222222222".to_string()), // Different
            offset: Some(200),                         // Different
            set: None,                                 // Different
            set_once: Some(HashMap::new()),            // Different
        };

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        // These events are completely different
        assert!(similarity.different_field_count >= 5); // Most fields differ
        assert_eq!(similarity.properties_similarity, 0.0); // No common properties
        assert!(similarity.overall_score < 0.3); // Very low overall similarity
    }
}
