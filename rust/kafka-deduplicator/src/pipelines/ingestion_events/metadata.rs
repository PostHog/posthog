//! Metadata implementation for ingestion events.

use anyhow::Result;
use common_types::RawEvent;

use crate::pipelines::traits::DeduplicationMetadata;
use crate::rocksdb::dedup_metadata::EventSimilarity;
use crate::store::metadata::TimestampMetadata;

impl DeduplicationMetadata<RawEvent> for TimestampMetadata {
    fn new(event: &RawEvent) -> Self {
        TimestampMetadata::new(event)
    }

    fn update_duplicate(&mut self, new_event: &RawEvent) {
        TimestampMetadata::update_duplicate(self, new_event)
    }

    fn get_original_event(&self) -> Result<RawEvent> {
        TimestampMetadata::get_original_event(self)
    }

    fn calculate_similarity(&self, new_event: &RawEvent) -> Result<EventSimilarity> {
        TimestampMetadata::calculate_similarity(self, new_event)
    }

    fn to_bytes(&self) -> Result<Vec<u8>> {
        bincode::serde::encode_to_vec(self, bincode::config::standard())
            .map_err(|e| anyhow::anyhow!("Failed to serialize metadata: {}", e))
    }

    fn from_bytes(bytes: &[u8]) -> Result<Self> {
        bincode::serde::decode_from_slice(bytes, bincode::config::standard())
            .map(|(m, _)| m)
            .map_err(|e| anyhow::anyhow!("Failed to deserialize metadata: {}", e))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use uuid::Uuid;

    fn create_test_event(uuid: Option<Uuid>) -> RawEvent {
        RawEvent {
            uuid,
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token456".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_metadata_creation_via_trait() {
        let uuid = Uuid::new_v4();
        let event = create_test_event(Some(uuid));

        let metadata = <TimestampMetadata as DeduplicationMetadata<RawEvent>>::new(&event);

        assert_eq!(metadata.duplicate_count, 0);
        assert!(metadata.seen_uuids.contains(&uuid.to_string()));
    }

    #[test]
    fn test_metadata_serialization_roundtrip() {
        let event = create_test_event(Some(Uuid::new_v4()));
        let metadata = <TimestampMetadata as DeduplicationMetadata<RawEvent>>::new(&event);

        let bytes = metadata.to_bytes().unwrap();
        let restored =
            <TimestampMetadata as DeduplicationMetadata<RawEvent>>::from_bytes(&bytes).unwrap();

        assert_eq!(metadata.duplicate_count, restored.duplicate_count);
        assert_eq!(metadata.seen_uuids, restored.seen_uuids);
    }

    #[test]
    fn test_metadata_update_duplicate() {
        let event1 = create_test_event(Some(Uuid::new_v4()));
        let event2 = create_test_event(Some(Uuid::new_v4()));

        let mut metadata = <TimestampMetadata as DeduplicationMetadata<RawEvent>>::new(&event1);
        metadata.update_duplicate(&event2);

        assert_eq!(metadata.duplicate_count, 1);
        assert_eq!(metadata.seen_uuids.len(), 2);
    }

    #[test]
    fn test_get_original_event() {
        let uuid = Uuid::new_v4();
        let event = create_test_event(Some(uuid));

        let metadata = <TimestampMetadata as DeduplicationMetadata<RawEvent>>::new(&event);
        let original = metadata.get_original_event().unwrap();

        assert_eq!(original.event, "test_event");
        assert_eq!(original.uuid, Some(uuid));
    }

    #[test]
    fn test_calculate_similarity_identical() {
        let uuid = Uuid::new_v4();
        let event = create_test_event(Some(uuid));

        let metadata = <TimestampMetadata as DeduplicationMetadata<RawEvent>>::new(&event);
        let similarity = metadata.calculate_similarity(&event).unwrap();

        assert_eq!(similarity.overall_score, 1.0);
    }
}
