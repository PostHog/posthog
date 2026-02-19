//! Parser for ClickHouse events.
//!
//! Unlike the ingestion_events pipeline where CapturedEvent is transformed to RawEvent,
//! the clickhouse_events pipeline uses the wire format directly since ClickHouseEvent
//! already contains all needed fields for deduplication.

use anyhow::Result;
use common_types::ClickHouseEvent;

use crate::kafka::batch_message::KafkaMessage;
use crate::pipelines::traits::EventParser;

/// Parser for ClickHouse events from the `clickhouse_events_json` topic.
///
/// This parser performs no transformation.
/// The clone is necessary because the trait requires returning an owned value,
/// and the event will be stored in metadata which also requires ownership.
pub struct ClickHouseEventParser;

impl EventParser<ClickHouseEvent, ClickHouseEvent> for ClickHouseEventParser {
    fn parse(message: &KafkaMessage<ClickHouseEvent>) -> Result<ClickHouseEvent> {
        message
            .get_message()
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("No message payload in KafkaMessage"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::types::Partition;
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
    fn test_parser_returns_event() {
        let event = create_test_event();
        let message = KafkaMessage::new_for_test(
            Partition::new("test-topic".to_string(), 0),
            0,
            event.clone(),
        );

        let parsed = ClickHouseEventParser::parse(&message).unwrap();

        assert_eq!(parsed.uuid, event.uuid);
        assert_eq!(parsed.team_id, event.team_id);
        assert_eq!(parsed.event, event.event);
        assert_eq!(parsed.distinct_id, event.distinct_id);
        assert_eq!(parsed.timestamp, event.timestamp);
    }

    #[test]
    fn test_parser_returns_error_on_missing_message() {
        let message: KafkaMessage<ClickHouseEvent> = KafkaMessage::new(
            Partition::new("test-topic".to_string(), 0),
            42,
            None,
            None, // No message
            std::time::SystemTime::now(),
            None,
            None,
        );

        let result = ClickHouseEventParser::parse(&message);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("No message payload"));
    }
}
