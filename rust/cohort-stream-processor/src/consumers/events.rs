//! The `cohort_stream_events` wire envelope (TDD §4.3), processor side.
//!
//! This is the processor's **own** deserialize struct — deliberately decoupled from
//! `cohort-event-shuffler`'s producer type (`cohort-event-shuffler/src/event.rs:30-42`). The two
//! services share only the JSON field names on the wire; the shuffler comment at `event.rs:25`
//! anticipates exactly this split. Keeping a private copy means neither service can break the
//! other by adding a producer-only or consumer-only field.
//!
//! PR 1.4 ships **only the struct** so `hogvm::globals` has the event shape to port against. The
//! rdkafka `StreamConsumer` that decodes the topic and feeds the partition router is PR 1.7.

use serde::Deserialize;

/// One re-keyed event as published to `cohort_stream_events`. Field names mirror TDD §4.3 and the
/// shuffler envelope exactly so this deserializes the same bytes the shuffler emits.
///
/// `properties` / `person_properties` are raw, unparsed JSON strings (as stored in
/// `clickhouse_events_json`); [`crate::hogvm::globals`] parses them lazily so a malformed payload
/// can skip a single event without failing the deserialize. `source_partition` / `source_offset`
/// carry the upstream coordinates Stage 1 (PR 1.6) uses for replay-safe counter increments.
#[derive(Debug, Clone, Deserialize)]
pub struct CohortStreamEvent {
    pub team_id: i32,
    pub person_id: String,
    pub distinct_id: String,
    pub uuid: String,
    pub event: String,
    /// ClickHouse wire format `"YYYY-MM-DD HH:MM:SS.ffffff"`; normalized to ISO 8601 when the
    /// globals dict is built (matching Node's `convertClickhouseRawEventToFilterGlobals`).
    pub timestamp: String,
    /// Raw event-properties JSON, or `None` when the source column was null.
    pub properties: Option<String>,
    /// Raw person-properties JSON, or `None` when the source column was null.
    pub person_properties: Option<String>,
    pub elements_chain: Option<String>,
    pub source_offset: i64,
    pub source_partition: i32,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn deserializes_a_full_shuffler_envelope() {
        // The exact key set the shuffler emits (TDD §4.3) must round-trip into this struct.
        let value = json!({
            "team_id": 42,
            "person_id": "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "distinct_id": "user@example.com",
            "uuid": "0192f00d-f00d-f00d-f00d-f00df00df00d",
            "event": "$pageview",
            "timestamp": "2026-05-26 12:34:56.789000",
            "properties": "{\"$browser\":\"Chrome\"}",
            "person_properties": "{\"email\":\"u@p.com\"}",
            "elements_chain": "a:href=\"/x\"",
            "source_offset": 12345,
            "source_partition": 17,
        });

        let event: CohortStreamEvent = serde_json::from_value(value).unwrap();
        assert_eq!(event.team_id, 42);
        assert_eq!(event.person_id, "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        assert_eq!(event.event, "$pageview");
        assert_eq!(
            event.properties.as_deref(),
            Some("{\"$browser\":\"Chrome\"}")
        );
        assert_eq!(event.source_offset, 12345);
        assert_eq!(event.source_partition, 17);
    }

    #[test]
    fn null_optional_payloads_deserialize_to_none() {
        let value = json!({
            "team_id": 1,
            "person_id": "p",
            "distinct_id": "d",
            "uuid": "u",
            "event": "$pageview",
            "timestamp": "2026-05-26 12:34:56.789000",
            "properties": null,
            "person_properties": null,
            "elements_chain": null,
            "source_offset": 0,
            "source_partition": 0,
        });

        let event: CohortStreamEvent = serde_json::from_value(value).unwrap();
        assert!(event.properties.is_none());
        assert!(event.person_properties.is_none());
        assert!(event.elements_chain.is_none());
    }
}
