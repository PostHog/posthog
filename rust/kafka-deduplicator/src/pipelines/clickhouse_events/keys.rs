//! Deduplication key extraction for ClickHouse events.

use anyhow::{Context, Result};
use common_types::ClickHouseEvent;

use crate::pipelines::traits::DeduplicationKeyExtractor;
use crate::store::keys::TimestampKey;
use crate::utils::timestamp::parse_clickhouse_timestamp;

impl DeduplicationKeyExtractor for ClickHouseEvent {
    fn extract_dedup_key(&self) -> Vec<u8> {
        let key = TimestampKey::try_from(self).expect("ClickHouseEvent must have valid timestamp");
        (&key).into()
    }
}

impl TryFrom<&ClickHouseEvent> for TimestampKey {
    type Error = anyhow::Error;

    fn try_from(event: &ClickHouseEvent) -> Result<Self> {
        let timestamp = parse_clickhouse_timestamp(&event.timestamp).with_context(|| {
            format!(
                "Failed to parse ClickHouse timestamp '{}' for event {}",
                event.timestamp, event.uuid
            )
        })?;

        Ok(Self::new(
            timestamp,
            event.distinct_id.clone(),
            event.team_id.to_string(),
            event.event.clone(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::PersonMode;
    use uuid::Uuid;

    fn create_test_event() -> ClickHouseEvent {
        ClickHouseEvent {
            uuid: Uuid::new_v4(),
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
    fn test_clickhouse_event_dedup_key_extraction() {
        let event = create_test_event();
        let key_bytes = event.extract_dedup_key();

        assert!(!key_bytes.is_empty());
        assert!(key_bytes.len() > 8); // At least 8 bytes for timestamp plus some data
    }

    #[test]
    fn test_same_event_produces_same_key() {
        let event1 = create_test_event();
        let mut event2 = create_test_event();
        event2.uuid = Uuid::new_v4(); // Different UUID

        // Same dedup key despite different UUIDs
        assert_eq!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_different_events_produce_different_keys() {
        let event1 = create_test_event();
        let mut event2 = create_test_event();
        event2.event = "different_event".to_string();

        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_different_team_ids_produce_different_keys() {
        let event1 = create_test_event();
        let mut event2 = create_test_event();
        event2.team_id = 999;

        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_different_distinct_ids_produce_different_keys() {
        let event1 = create_test_event();
        let mut event2 = create_test_event();
        event2.distinct_id = "different_user".to_string();

        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_different_timestamps_produce_different_keys() {
        let event1 = create_test_event();
        let mut event2 = create_test_event();
        event2.timestamp = "2024-01-01 12:00:01.000000".to_string(); // 1 second later

        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_timestamp_key_roundtrip() {
        let event = create_test_event();
        let key = TimestampKey::try_from(&event).unwrap();

        let key_bytes: Vec<u8> = (&key).into();
        let parsed_key = TimestampKey::try_from(key_bytes.as_slice()).unwrap();

        assert_eq!(key.timestamp, parsed_key.timestamp);
        assert_eq!(key.distinct_id, parsed_key.distinct_id);
        assert_eq!(key.token, parsed_key.token); // team_id as string
        assert_eq!(key.event_name, parsed_key.event_name);
    }

    #[test]
    fn test_team_id_used_as_token() {
        let event = create_test_event();
        let key = TimestampKey::try_from(&event).unwrap();

        assert_eq!(key.token, "123"); // team_id converted to string
    }

    #[test]
    fn test_invalid_timestamp_returns_error() {
        let mut event = create_test_event();
        event.timestamp = "not-a-valid-timestamp".to_string();

        let result = TimestampKey::try_from(&event);
        assert!(result.is_err());
    }

    #[test]
    #[should_panic(expected = "ClickHouseEvent must have valid timestamp")]
    fn test_extract_dedup_key_panics_on_invalid_timestamp() {
        let mut event = create_test_event();
        event.timestamp = "invalid".to_string();
        event.extract_dedup_key();
    }
}
