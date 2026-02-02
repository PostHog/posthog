//! Deduplication key extraction for ingestion events.

use common_types::RawEvent;

use crate::store::keys::{DeduplicationKeyExtractor, TimestampKey};

impl DeduplicationKeyExtractor for RawEvent {
    fn extract_dedup_key(&self) -> Vec<u8> {
        let key = TimestampKey::from(self);
        (&key).into()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn create_test_event() -> RawEvent {
        RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token456".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_raw_event_dedup_key_extraction() {
        let event = create_test_event();
        let key_bytes = event.extract_dedup_key();

        // Key should be non-empty
        assert!(!key_bytes.is_empty());

        // Should be at least 8 bytes (timestamp) plus some data
        assert!(key_bytes.len() > 8);
    }

    #[test]
    fn test_same_event_produces_same_key() {
        let event1 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()), // Different UUID
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        // Same dedup key despite different UUIDs
        assert_eq!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_different_events_produce_different_keys() {
        let event1 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "button_click".to_string(), // Different event name
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }
}
