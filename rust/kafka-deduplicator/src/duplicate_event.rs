use crate::store::deduplication_store::DeduplicationResult;
use common_types::RawEvent;
use serde::{Deserialize, Serialize, Serializer};

/// Helper function to serialize bool as u8 (0 or 1) for ClickHouse UInt8
fn serialize_bool_as_u8<S>(value: &bool, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    serializer.serialize_u8(if *value { 1 } else { 0 })
}

/// Represents a duplicate event detection result for publishing to Kafka
#[derive(Debug, Serialize, Deserialize)]
pub struct DuplicateEvent {
    /// Team ID extracted from the event
    pub team_id: Option<i64>,

    /// Distinct ID from the event
    pub distinct_id: String,

    /// Event name
    pub event: String,

    /// UUID of the source event (the new duplicate)
    pub source_uuid: Option<uuid::Uuid>,

    /// UUID of the original event (the first occurrence)
    pub duplicate_uuid: Option<uuid::Uuid>,

    /// Overall similarity score (0.0-1.0)
    pub similarity_score: f64,

    /// Type of duplication detected
    #[serde(rename = "dedup_type")]
    pub dedup_type: String, // "timestamp" or "uuid"

    /// Whether this is a confirmed duplicate
    #[serde(rename = "is_confirmed", serialize_with = "serialize_bool_as_u8")]
    pub is_confirmed: bool,

    /// Optional reason for confirmed duplicates
    pub reason: Option<String>,

    /// Algorithm version for A/B testing
    pub version: String,

    /// Number of properties that differ
    pub different_property_count: u32,

    /// Properties similarity score
    pub properties_similarity: f64,

    /// The current event that was detected as a duplicate (as JSON)
    pub source_message: serde_json::Value,

    /// The first occurrence of this event (from metadata) (as JSON)
    pub duplicate_message: serde_json::Value,

    /// List of fields that differ between the events (as JSON array)
    pub distinct_fields: serde_json::Value,

    /// Timestamp when this duplicate was detected
    pub inserted_at: String, // ISO8601 timestamp
}

/// Represents a field that differs between two events
#[derive(Debug, Serialize, Deserialize)]
pub struct DifferentField {
    pub field_name: String,
    pub original_value: String,
    pub new_value: String,
}

impl DuplicateEvent {
    /// Create a DuplicateEvent from deduplication result (which includes similarity data)
    pub fn from_result(source_event: &RawEvent, result: &DeduplicationResult) -> Option<Self> {
        // Extract similarity from the result
        let similarity = result.get_similarity()?;

        let (dedup_type, is_confirmed, reason, original_event) = match result {
            DeduplicationResult::ConfirmedDuplicate(dtype, dreason, _, original_event) => (
                dtype.to_string().to_lowercase(),
                true,
                Some(dreason.to_string()),
                original_event,
            ),
            DeduplicationResult::PotentialDuplicate(dtype, _, original_event) => (
                dtype.to_string().to_lowercase(),
                false,
                None,
                original_event,
            ),
            _ => {
                // New and Skipped don't have similarity data
                return None;
            }
        };

        // For now, leave as None
        let team_id = None;

        // Extract distinct_id
        let distinct_id = source_event
            .extract_distinct_id()
            .unwrap_or_else(|| "".to_string());

        // Extract event name
        let event = source_event.event.clone();

        // Extract UUIDs
        let source_uuid = source_event.uuid;
        let duplicate_uuid = original_event.uuid;

        // Convert distinct_fields to a JSON array
        let distinct_fields_vec: Vec<DifferentField> = similarity
            .different_fields
            .iter()
            .map(|(field_name, original, new)| DifferentField {
                field_name: field_name.to_string(),
                original_value: original.clone(),
                new_value: new.clone(),
            })
            .collect();

        let distinct_fields = serde_json::to_value(&distinct_fields_vec).ok()?;

        // Serialize the events to JSON values
        let source_message = serde_json::to_value(source_event).ok()?;
        let duplicate_message = serde_json::to_value(original_event).ok()?;

        // Generate current timestamp in ISO8601 format for ClickHouse DateTime64
        let inserted_at = chrono::Utc::now()
            .format("%Y-%m-%d %H:%M:%S%.3f")
            .to_string();

        Some(DuplicateEvent {
            team_id,
            distinct_id,
            event,
            source_uuid,
            duplicate_uuid,
            similarity_score: similarity.overall_score,
            dedup_type,
            is_confirmed,
            reason,
            version: "1.0.0".to_string(),
            different_property_count: similarity.different_property_count,
            properties_similarity: similarity.properties_similarity,
            source_message,
            duplicate_message,
            distinct_fields,
            inserted_at,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rocksdb::dedup_metadata::{DedupFieldName, EventSimilarity};
    use crate::store::deduplication_store::{DeduplicationResultReason, DeduplicationType};
    use serde_json::json;

    #[test]
    fn test_duplicate_event_serialization() {
        use std::collections::HashMap;
        use uuid::Uuid;

        let mut source_props = HashMap::new();
        source_props.insert("$browser".to_string(), json!("Chrome"));

        let source_event = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "$pageview".to_string(),
            distinct_id: Some("user123".into()),
            timestamp: Some("2024-01-01T12:00:00Z".to_string()),
            token: Some("test-token".to_string()),
            properties: source_props,
            ..Default::default()
        };

        let mut original_props = HashMap::new();
        original_props.insert("$browser".to_string(), json!("Firefox"));

        // Create event for returning from result
        let result_event = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "$pageview".to_string(),
            distinct_id: Some("user123".into()),
            timestamp: Some("2024-01-01T12:00:00Z".to_string()),
            token: Some("test-token".to_string()),
            properties: original_props.clone(),
            ..Default::default()
        };

        let similarity = EventSimilarity {
            overall_score: 0.9,
            different_field_count: 1,
            different_fields: vec![(
                DedupFieldName::Uuid,
                "uuid-2".to_string(),
                "uuid-1".to_string(),
            )],
            properties_similarity: 0.8,
            different_property_count: 1,
            different_properties: vec![],
        };

        let result = DeduplicationResult::ConfirmedDuplicate(
            DeduplicationType::Timestamp,
            DeduplicationResultReason::OnlyUuidDifferent,
            similarity,
            result_event,
        );

        let duplicate_event = DuplicateEvent::from_result(&source_event, &result).unwrap();

        // Verify the fields
        assert!(duplicate_event.is_confirmed);
        assert_eq!(duplicate_event.dedup_type, "timestamp");
        assert_eq!(
            duplicate_event.reason,
            Some("OnlyUuidDifferent".to_string())
        );
        assert_eq!(duplicate_event.similarity_score, 0.9);

        // Verify distinct_fields is a JSON array with 1 element
        if let serde_json::Value::Array(arr) = &duplicate_event.distinct_fields {
            assert_eq!(arr.len(), 1);
        } else {
            panic!("distinct_fields should be a JSON array");
        }

        assert_eq!(duplicate_event.different_property_count, 1);
        assert_eq!(duplicate_event.properties_similarity, 0.8);

        // Verify new fields are present
        assert_eq!(duplicate_event.distinct_id, "user123");
        assert_eq!(duplicate_event.event, "$pageview");
        assert!(duplicate_event.source_uuid.is_some());
        assert!(duplicate_event.duplicate_uuid.is_some());
        assert!(!duplicate_event.inserted_at.is_empty());

        // Test serialization
        let json = serde_json::to_string(&duplicate_event).unwrap();
        assert!(json.contains("\"dedup_type\":\"timestamp\""));
        assert!(json.contains("\"is_confirmed\":1")); // Serialized as u8
    }

    #[test]
    fn test_potential_duplicate_event() {
        let source_event = RawEvent::default();
        let result_event = RawEvent::default();

        let similarity = EventSimilarity {
            overall_score: 0.7,
            different_field_count: 2,
            different_fields: vec![],
            properties_similarity: 0.5,
            different_property_count: 3,
            different_properties: vec![],
        };

        let result = DeduplicationResult::PotentialDuplicate(
            DeduplicationType::UUID,
            similarity,
            result_event,
        );

        let duplicate_event = DuplicateEvent::from_result(&source_event, &result).unwrap();

        assert!(!duplicate_event.is_confirmed);
        assert_eq!(duplicate_event.dedup_type, "uuid");
        assert!(duplicate_event.reason.is_none());
        assert_eq!(duplicate_event.similarity_score, 0.7);
    }
}
