//! Metadata storage for ClickHouse events deduplication.
//!
//! This module tracks:
//! - The original event (for reference and similarity comparison)
//! - Seen UUIDs (to detect retries with same/different UUIDs)
//! - Duplicate count

use std::collections::HashSet;

use anyhow::{anyhow, Result};
use common_types::{ClickHouseEvent, PersonMode};
use serde::{Deserialize, Serialize};

use crate::pipelines::results::EventSimilarity;
use crate::pipelines::traits::DeduplicationMetadata;

/// Serializable version of ClickHouseEvent for bincode storage.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SerializableClickHouseEvent {
    pub uuid: String,
    pub team_id: i32,
    pub project_id: Option<i64>,
    pub event: String,
    pub distinct_id: String,
    pub properties: Option<String>,
    pub person_id: Option<String>,
    pub timestamp: String,
    pub created_at: String,
}

impl From<&ClickHouseEvent> for SerializableClickHouseEvent {
    fn from(event: &ClickHouseEvent) -> Self {
        Self {
            uuid: event.uuid.to_string(),
            team_id: event.team_id,
            project_id: event.project_id,
            event: event.event.clone(),
            distinct_id: event.distinct_id.clone(),
            properties: event.properties.clone(),
            person_id: event.person_id.clone(),
            timestamp: event.timestamp.clone(),
            created_at: event.created_at.clone(),
        }
    }
}

impl TryFrom<&SerializableClickHouseEvent> for ClickHouseEvent {
    type Error = anyhow::Error;

    fn try_from(serializable: &SerializableClickHouseEvent) -> Result<Self> {
        let uuid = serializable
            .uuid
            .parse()
            .map_err(|e| anyhow!("Invalid UUID: {e}"))?;

        Ok(ClickHouseEvent {
            uuid,
            team_id: serializable.team_id,
            project_id: serializable.project_id,
            event: serializable.event.clone(),
            distinct_id: serializable.distinct_id.clone(),
            properties: serializable.properties.clone(),
            person_id: serializable.person_id.clone(),
            timestamp: serializable.timestamp.clone(),
            created_at: serializable.created_at.clone(),
            captured_at: None,
            elements_chain: None,
            person_created_at: None,
            person_properties: None,
            group0_properties: None,
            group1_properties: None,
            group2_properties: None,
            group3_properties: None,
            group4_properties: None,
            group0_created_at: None,
            group1_created_at: None,
            group2_created_at: None,
            group3_created_at: None,
            group4_created_at: None,
            person_mode: PersonMode::Full,
            historical_migration: None,
        })
    }
}

/// Metadata for tracking ClickHouse event duplicates.
#[derive(Serialize, Deserialize, Debug)]
pub struct ClickHouseEventMetadata {
    /// Original event data (minimal fields for reference)
    pub original_event: SerializableClickHouseEvent,
    /// Set of UUIDs seen for this dedup key
    pub seen_uuids: HashSet<String>,
    /// Count of duplicate events
    pub duplicate_count: u64,
}

impl ClickHouseEventMetadata {
    /// Create new metadata for the first occurrence of an event.
    pub fn new(event: &ClickHouseEvent) -> Self {
        let mut seen_uuids = HashSet::new();
        seen_uuids.insert(event.uuid.to_string());

        Self {
            original_event: SerializableClickHouseEvent::from(event),
            seen_uuids,
            duplicate_count: 0,
        }
    }

    /// Update metadata when a duplicate is detected.
    pub fn update_duplicate(&mut self, new_event: &ClickHouseEvent) {
        self.duplicate_count += 1;
        self.seen_uuids.insert(new_event.uuid.to_string());
    }

    /// Get the original ClickHouseEvent.
    pub fn get_original_event(&self) -> Result<ClickHouseEvent> {
        ClickHouseEvent::try_from(&self.original_event)
    }

    /// Calculate similarity with another event.
    pub fn calculate_similarity(&self, new_event: &ClickHouseEvent) -> Result<EventSimilarity> {
        let original_event = self.get_original_event()?;
        EventSimilarity::calculate(&original_event, new_event)
    }

    /// Serialize metadata to bytes for RocksDB storage.
    pub fn to_bytes(&self) -> Result<Vec<u8>> {
        bincode::serde::encode_to_vec(self, bincode::config::standard())
            .map_err(|e| anyhow::anyhow!("Failed to serialize ClickHouseEventMetadata: {}", e))
    }

    /// Deserialize metadata from bytes.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        bincode::serde::decode_from_slice(bytes, bincode::config::standard())
            .map(|(m, _)| m)
            .map_err(|e| anyhow::anyhow!("Failed to deserialize ClickHouseEventMetadata: {}", e))
    }

    /// Check if this is a confirmed duplicate (same UUID seen before).
    pub fn is_same_uuid(&self, event: &ClickHouseEvent) -> bool {
        self.seen_uuids.contains(&event.uuid.to_string())
    }
}

impl DeduplicationMetadata<ClickHouseEvent> for ClickHouseEventMetadata {
    fn new(event: &ClickHouseEvent) -> Self {
        ClickHouseEventMetadata::new(event)
    }

    fn update_duplicate(&mut self, new_event: &ClickHouseEvent) {
        ClickHouseEventMetadata::update_duplicate(self, new_event)
    }

    fn get_original_event(&self) -> Result<ClickHouseEvent> {
        ClickHouseEventMetadata::get_original_event(self)
    }

    fn calculate_similarity(&self, new_event: &ClickHouseEvent) -> Result<EventSimilarity> {
        ClickHouseEventMetadata::calculate_similarity(self, new_event)
    }

    fn unique_uuids_count(&self) -> usize {
        self.seen_uuids.len()
    }

    fn to_bytes(&self) -> Result<Vec<u8>> {
        ClickHouseEventMetadata::to_bytes(self)
    }

    fn from_bytes(bytes: &[u8]) -> Result<Self> {
        ClickHouseEventMetadata::from_bytes(bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::PersonMode;
    use uuid::Uuid;

    fn create_test_event(uuid: Uuid) -> ClickHouseEvent {
        ClickHouseEvent {
            uuid,
            team_id: 123,
            project_id: Some(456),
            event: "test_event".to_string(),
            distinct_id: "user123".to_string(),
            properties: Some(r#"{"foo": "bar"}"#.to_string()),
            person_id: Some("person-uuid".to_string()),
            timestamp: "2024-01-01 12:00:00.000000".to_string(),
            created_at: "2024-01-01 12:00:00.000000".to_string(),
            captured_at: None,
            elements_chain: None,
            person_created_at: None,
            person_properties: None,
            group0_properties: None,
            group1_properties: None,
            group2_properties: None,
            group3_properties: None,
            group4_properties: None,
            group0_created_at: None,
            group1_created_at: None,
            group2_created_at: None,
            group3_created_at: None,
            group4_created_at: None,
            person_mode: PersonMode::Full,
            historical_migration: None,
        }
    }

    #[test]
    fn test_metadata_creation() {
        let uuid = Uuid::new_v4();
        let event = create_test_event(uuid);
        let metadata = ClickHouseEventMetadata::new(&event);

        assert_eq!(metadata.duplicate_count, 0);
        assert_eq!(metadata.seen_uuids.len(), 1);
        assert!(metadata.seen_uuids.contains(&uuid.to_string()));
        assert_eq!(metadata.original_event.team_id, 123);
        assert_eq!(metadata.original_event.event, "test_event");
    }

    #[test]
    fn test_metadata_update_duplicate() {
        let uuid1 = Uuid::new_v4();
        let uuid2 = Uuid::new_v4();

        let event1 = create_test_event(uuid1);
        let event2 = create_test_event(uuid2);

        let mut metadata = ClickHouseEventMetadata::new(&event1);
        metadata.update_duplicate(&event2);

        assert_eq!(metadata.duplicate_count, 1);
        assert_eq!(metadata.seen_uuids.len(), 2);
        assert!(metadata.seen_uuids.contains(&uuid1.to_string()));
        assert!(metadata.seen_uuids.contains(&uuid2.to_string()));
    }

    #[test]
    fn test_metadata_same_uuid_detection() {
        let uuid = Uuid::new_v4();
        let event = create_test_event(uuid);
        let metadata = ClickHouseEventMetadata::new(&event);

        // Same UUID should be detected
        assert!(metadata.is_same_uuid(&event));

        // Different UUID should not be detected
        let different_event = create_test_event(Uuid::new_v4());
        assert!(!metadata.is_same_uuid(&different_event));
    }

    #[test]
    fn test_metadata_serialization_roundtrip() {
        let uuid = Uuid::new_v4();
        let event = create_test_event(uuid);
        let metadata = ClickHouseEventMetadata::new(&event);

        let bytes = metadata.to_bytes().unwrap();
        let restored = ClickHouseEventMetadata::from_bytes(&bytes).unwrap();

        assert_eq!(metadata.duplicate_count, restored.duplicate_count);
        assert_eq!(metadata.seen_uuids, restored.seen_uuids);
        assert_eq!(metadata.original_event.uuid, restored.original_event.uuid);
        assert_eq!(
            metadata.original_event.team_id,
            restored.original_event.team_id
        );
    }

    #[test]
    fn test_metadata_multiple_duplicates() {
        let uuid1 = Uuid::new_v4();
        let event1 = create_test_event(uuid1);
        let mut metadata = ClickHouseEventMetadata::new(&event1);

        // Add 5 duplicates with different UUIDs
        for _ in 0..5 {
            let dup_event = create_test_event(Uuid::new_v4());
            metadata.update_duplicate(&dup_event);
        }

        assert_eq!(metadata.duplicate_count, 5);
        assert_eq!(metadata.seen_uuids.len(), 6); // 1 original + 5 duplicates

        // Add duplicate with same UUID as original (retry scenario)
        metadata.update_duplicate(&event1);
        assert_eq!(metadata.duplicate_count, 6);
        assert_eq!(metadata.seen_uuids.len(), 6); // Still 6, same UUID
    }
}
