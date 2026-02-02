//! Event parser for ingestion events (CapturedEvent -> RawEvent).

use anyhow::Result;
use common_types::{CapturedEvent, RawEvent};
use tracing::{debug, error};

use crate::event_parser::EventParser;
use crate::kafka::batch_message::KafkaMessage;
use crate::utils::timestamp;

/// Parser for ingestion events.
///
/// Transforms `CapturedEvent` (the wire format from capture service)
/// into `RawEvent` (the domain event used for deduplication).
pub struct IngestionEventParser;

impl EventParser<CapturedEvent, RawEvent> for IngestionEventParser {
    fn parse(message: &KafkaMessage<CapturedEvent>) -> Result<RawEvent> {
        let captured_event = match message.get_message() {
            Some(captured_event) => captured_event,
            None => {
                error!(
                    "Failed to extract CapturedEvent from KafkaMessage at {}:{} offset {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset()
                );

                return Err(anyhow::anyhow!(
                    "Failed to extract CapturedEvent from KafkaMessage at {}:{} offset {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset(),
                ));
            }
        };

        // Extract well-validated values from the CapturedEvent that
        // may or may not be present in the wrapped RawEvent
        let now = captured_event.now.clone();
        let extracted_distinct_id = captured_event.distinct_id.clone();
        let extracted_token = captured_event.token.clone();
        let extracted_uuid = captured_event.uuid;

        // The RawEvent is serialized in the data field
        match serde_json::from_str::<RawEvent>(&captured_event.data) {
            Ok(mut raw_event) => {
                // Validate timestamp: if it's None or unparseable, use CapturedEvent.now
                // This ensures we always have a valid timestamp for deduplication
                match raw_event.timestamp {
                    None => {
                        debug!("No timestamp in RawEvent, using CapturedEvent.now");
                        raw_event.timestamp = Some(now);
                    }
                    Some(ref ts) if !timestamp::is_valid_timestamp(ts) => {
                        debug!(
                            "Invalid timestamp detected at {}:{} offset {}, replacing with CapturedEvent.now",
                            message.get_topic_partition().topic(),
                            message.get_topic_partition().partition_number(),
                            message.get_offset()
                        );
                        raw_event.timestamp = Some(now);
                    }
                    _ => {
                        // Timestamp exists and is valid, keep it
                    }
                }

                // If RawEvent is missing any of the core values
                // extracted by capture into the CapturedEvent
                // wrapper, use those values for downstream analysis
                if raw_event.uuid.is_none() {
                    raw_event.uuid = Some(extracted_uuid);
                }
                if raw_event.distinct_id.is_none() && !extracted_distinct_id.is_empty() {
                    raw_event.distinct_id = Some(serde_json::Value::String(extracted_distinct_id));
                }
                if raw_event.token.is_none() && !extracted_token.is_empty() {
                    raw_event.token = Some(extracted_token);
                }

                Ok(raw_event)
            }
            Err(e) => {
                error!(
                    "Failed to parse RawEvent from data field at {}:{} offset {}: {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset(),
                    e
                );
                Err(anyhow::anyhow!(
                    "Failed to parse RawEvent from data field at {}:{} offset {}: {}",
                    message.get_topic_partition().topic(),
                    message.get_topic_partition().partition_number(),
                    message.get_offset(),
                    e
                ))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::types::Partition;
    use uuid::Uuid;

    fn create_test_captured_event(data: &str) -> CapturedEvent {
        CapturedEvent {
            uuid: Uuid::new_v4(),
            distinct_id: "test_user".to_string(),
            session_id: None,
            ip: "127.0.0.1".to_string(),
            now: "2024-01-01T00:00:00Z".to_string(),
            token: "test_token".to_string(),
            data: data.to_string(),
            sent_at: None,
            event: "test_event".to_string(),
            timestamp: chrono::Utc::now(),
            is_cookieless_mode: false,
            historical_migration: false,
        }
    }

    #[test]
    fn test_parse_valid_event() {
        let data = r#"{"event": "page_view", "properties": {}}"#;
        let captured = create_test_captured_event(data);
        let message =
            KafkaMessage::new_for_test(Partition::new("test-topic".to_string(), 0), 0, captured);

        let result = IngestionEventParser::parse(&message);
        assert!(result.is_ok());

        let raw_event = result.unwrap();
        assert_eq!(raw_event.event, "page_view");
        // UUID should be filled from CapturedEvent
        assert!(raw_event.uuid.is_some());
        // Token should be filled from CapturedEvent
        assert_eq!(raw_event.token, Some("test_token".to_string()));
    }

    #[test]
    fn test_parse_event_with_missing_timestamp() {
        let data = r#"{"event": "click", "properties": {}}"#;
        let captured = create_test_captured_event(data);
        let message =
            KafkaMessage::new_for_test(Partition::new("test-topic".to_string(), 0), 0, captured);

        let result = IngestionEventParser::parse(&message);
        assert!(result.is_ok());

        let raw_event = result.unwrap();
        // Timestamp should be filled from CapturedEvent.now
        assert_eq!(
            raw_event.timestamp,
            Some("2024-01-01T00:00:00Z".to_string())
        );
    }

    #[test]
    fn test_parse_invalid_json() {
        let data = r#"not valid json"#;
        let captured = create_test_captured_event(data);
        let message =
            KafkaMessage::new_for_test(Partition::new("test-topic".to_string(), 0), 0, captured);

        let result = IngestionEventParser::parse(&message);
        assert!(result.is_err());
    }
}
