use anyhow::Result;
use common_types::RawEvent;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

use crate::rocksdb::dedup_metadata::{EventSimilarity, SerializableRawEvent};

/// Metadata for timestamp-based deduplication
/// Tracks UUIDs and event variations for a given timestamp+distinct_id+token+event_name
#[derive(Serialize, Deserialize, Debug)]
pub struct TimestampMetadata {
    /// Original event data
    pub original_event: SerializableRawEvent,
    /// Set of UUIDs seen for this timestamp combination
    pub seen_uuids: HashSet<String>,
    /// Count of duplicate events
    pub duplicate_count: u64,
    /// Count of events with no UUID
    pub no_uuid_count: u64,
}

impl TimestampMetadata {
    pub fn new(event: &RawEvent) -> Self {
        let mut seen_uuids = HashSet::new();
        let mut no_uuid_count = 0;

        if let Some(uuid) = event.uuid {
            seen_uuids.insert(uuid.to_string());
        } else {
            no_uuid_count = 1;
        }

        Self {
            original_event: SerializableRawEvent::from(event),
            seen_uuids,
            duplicate_count: 0,
            no_uuid_count,
        }
    }

    pub fn update_duplicate(&mut self, new_event: &RawEvent) {
        self.duplicate_count += 1;

        if let Some(uuid) = new_event.uuid {
            self.seen_uuids.insert(uuid.to_string());
        } else {
            self.no_uuid_count += 1;
        }
    }

    /// Get the original RawEvent
    pub fn get_original_event(&self) -> Result<RawEvent> {
        RawEvent::try_from(&self.original_event)
    }

    /// Calculate similarity with another event
    pub fn calculate_similarity(&self, new_event: &RawEvent) -> Result<EventSimilarity> {
        let original_event = self.get_original_event()?;
        EventSimilarity::calculate(&original_event, new_event)
    }

    pub fn get_metrics_summary(&self) -> String {
        format!(
            "Duplicates: {}, Unique UUIDs: {}, No-UUID events: {}",
            self.duplicate_count,
            self.seen_uuids.len(),
            self.no_uuid_count
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_event_with_uuid_and_timestamp(
        uuid: Option<uuid::Uuid>,
        timestamp: &str,
    ) -> RawEvent {
        RawEvent {
            uuid,
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some(timestamp.to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_timestamp_metadata_creation() {
        let uuid = uuid::Uuid::new_v4();
        let event = create_test_event_with_uuid_and_timestamp(Some(uuid), "2021-01-01T00:00:00Z");
        let metadata = TimestampMetadata::new(&event);

        assert_eq!(metadata.duplicate_count, 0);
        assert_eq!(metadata.seen_uuids.len(), 1);
        assert!(metadata.seen_uuids.contains(&uuid.to_string()));
        assert_eq!(metadata.no_uuid_count, 0);
    }

    #[test]
    fn test_timestamp_metadata_no_uuid() {
        let event = create_test_event_with_uuid_and_timestamp(None, "2021-01-01T00:00:00Z");
        let metadata = TimestampMetadata::new(&event);

        assert_eq!(metadata.duplicate_count, 0);
        assert_eq!(metadata.seen_uuids.len(), 0);
        assert_eq!(metadata.no_uuid_count, 1);
    }

    #[test]
    fn test_timestamp_metadata_update() {
        let uuid1 = uuid::Uuid::new_v4();
        let uuid2 = uuid::Uuid::new_v4();

        let event1 = create_test_event_with_uuid_and_timestamp(Some(uuid1), "2021-01-01T00:00:00Z");
        let mut metadata = TimestampMetadata::new(&event1);

        let event2 = create_test_event_with_uuid_and_timestamp(Some(uuid2), "2021-01-01T00:00:00Z");
        metadata.update_duplicate(&event2);

        assert_eq!(metadata.duplicate_count, 1);
        assert_eq!(metadata.seen_uuids.len(), 2);
        assert!(metadata.seen_uuids.contains(&uuid1.to_string()));
        assert!(metadata.seen_uuids.contains(&uuid2.to_string()));
    }
}
