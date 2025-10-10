use crate::store::deduplication_store::DeduplicationResult;
use common_types::RawEvent;
use serde::{Deserialize, Serialize};

/// Represents a duplicate event detection result for publishing to Kafka
#[derive(Debug, Serialize, Deserialize)]
pub struct DuplicateEvent {
    /// The current event that was detected as a duplicate (as JSON)
    pub source_message: serde_json::Value,

    /// The first occurrence of this event (from metadata) (as JSON)
    pub duplicate_message: serde_json::Value,

    /// Overall similarity score (0.0-1.0)
    pub similarity_score: f64,

    /// List of fields that differ between the events
    pub distinct_fields: Vec<DifferentField>,

    /// Type of duplication detected
    #[serde(rename = "type")]
    pub dedup_type: String, // "timestamp" or "uuid"

    /// Whether this is a confirmed duplicate
    pub is_confirmed: bool,

    /// Optional reason for confirmed duplicates
    pub reason: Option<String>,

    /// Algorithm version for A/B testing
    pub version: String,

    /// Number of properties that differ
    pub different_property_count: u32,

    /// Properties similarity score
    pub properties_similarity: f64,
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

        let distinct_fields = similarity
            .different_fields
            .iter()
            .map(|(field_name, original, new)| DifferentField {
                field_name: field_name.to_string(),
                original_value: original.clone(),
                new_value: new.clone(),
            })
            .collect();

        // Serialize the events to JSON values to avoid cloning issues
        let source_json = serde_json::to_value(source_event).ok()?;
        let original_json = serde_json::to_value(original_event).ok()?;

        Some(DuplicateEvent {
            source_message: source_json,
            duplicate_message: original_json,
            similarity_score: similarity.overall_score,
            distinct_fields,
            dedup_type,
            is_confirmed,
            reason,
            version: "1.0.0".to_string(),
            different_property_count: similarity.different_property_count,
            properties_similarity: similarity.properties_similarity,
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
        assert_eq!(duplicate_event.distinct_fields.len(), 1);
        assert_eq!(duplicate_event.different_property_count, 1);
        assert_eq!(duplicate_event.properties_similarity, 0.8);

        // Test serialization
        let json = serde_json::to_string(&duplicate_event).unwrap();
        assert!(json.contains("\"type\":\"timestamp\""));
        assert!(json.contains("\"is_confirmed\":true"));
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
