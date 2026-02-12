//! Metadata implementation for ingestion events.

use anyhow::{anyhow, Result};
use common_types::RawEvent;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

use crate::pipelines::traits::DeduplicationMetadata;
use crate::pipelines::EventSimilarity;

/// Bincode-compatible version of RawEvent that stores JSON as strings.
///
/// This wrapper is necessary because bincode cannot directly serialize
/// `serde_json::Value` types. By converting JSON values to strings first,
/// we can efficiently serialize event data for RocksDB storage.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SerializableRawEvent {
    pub uuid: Option<String>,
    pub event: String,
    pub distinct_id_json: Option<String>,
    pub token: Option<String>,
    pub properties_json: String,
    pub timestamp: Option<String>,
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
            .map(|s| s.parse().map_err(|e| anyhow!("Invalid UUID: {e}")))
            .transpose()?;

        let distinct_id = serializable
            .distinct_id_json
            .as_ref()
            .map(|s| serde_json::from_str(s).map_err(|e| anyhow!("Invalid distinct_id JSON: {e}")))
            .transpose()?;

        let properties: HashMap<String, serde_json::Value> =
            serde_json::from_str(&serializable.properties_json)
                .map_err(|e| anyhow!("Invalid properties JSON: {e}"))?;

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

/// Metadata for timestamp-based deduplication.
///
/// Tracks UUIDs and event variations for a given timestamp+distinct_id+token+event_name
/// deduplication key.
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

    fn unique_uuids_count(&self) -> usize {
        self.seen_uuids.len()
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

    fn create_test_event_with_timestamp(uuid: Option<Uuid>, timestamp: &str) -> RawEvent {
        RawEvent {
            uuid,
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            properties: HashMap::new(),
            timestamp: Some(timestamp.to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_timestamp_metadata_creation() {
        let uuid = Uuid::new_v4();
        let event = create_test_event_with_timestamp(Some(uuid), "2021-01-01T00:00:00Z");
        let metadata = TimestampMetadata::new(&event);

        assert_eq!(metadata.duplicate_count, 0);
        assert_eq!(metadata.seen_uuids.len(), 1);
        assert!(metadata.seen_uuids.contains(&uuid.to_string()));
        assert_eq!(metadata.no_uuid_count, 0);
    }

    #[test]
    fn test_timestamp_metadata_no_uuid() {
        let event = create_test_event_with_timestamp(None, "2021-01-01T00:00:00Z");
        let metadata = TimestampMetadata::new(&event);

        assert_eq!(metadata.duplicate_count, 0);
        assert_eq!(metadata.seen_uuids.len(), 0);
        assert_eq!(metadata.no_uuid_count, 1);
    }

    #[test]
    fn test_timestamp_metadata_update() {
        let uuid1 = Uuid::new_v4();
        let uuid2 = Uuid::new_v4();

        let event1 = create_test_event_with_timestamp(Some(uuid1), "2021-01-01T00:00:00Z");
        let mut metadata = TimestampMetadata::new(&event1);

        let event2 = create_test_event_with_timestamp(Some(uuid2), "2021-01-01T00:00:00Z");
        metadata.update_duplicate(&event2);

        assert_eq!(metadata.duplicate_count, 1);
        assert_eq!(metadata.seen_uuids.len(), 2);
        assert!(metadata.seen_uuids.contains(&uuid1.to_string()));
        assert!(metadata.seen_uuids.contains(&uuid2.to_string()));
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
