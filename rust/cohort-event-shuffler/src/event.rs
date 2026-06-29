//! The `cohort_stream_events` envelope and the canonical re-key derivation.
//!
//! Forwards only the fields the downstream bytecode evaluation needs; group properties,
//! `person_mode`, `created_at`, `project_id` and similar are intentionally dropped.

use common_types::ClickHouseEvent;
use serde::{Deserialize, Serialize};

/// Single source of truth for the re-key string. Every producer targeting a topic co-partitioned
/// with `cohort_stream_events` must use this so a given `(team_id, person_id)` lands on the same
/// partition — and downstream worker — across topics and runtimes (Rust here, Node for
/// `person_merge_events`), given the shared `murmur2_random` partitioner and 64-partition count.
#[inline]
pub fn partition_key(team_id: i32, person_id: &str) -> String {
    format!("{team_id}:{person_id}")
}

/// `source_partition` / `source_offset` carry the upstream `clickhouse_events_json` coordinates so
/// the downstream processor can make counter increments replay-safe via per-key offset tracking.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CohortStreamEvent {
    pub team_id: i32,
    pub person_id: String,
    pub distinct_id: String,
    pub uuid: String,
    pub event: String,
    pub timestamp: String,
    pub properties: Option<String>,
    pub person_properties: Option<String>,
    pub elements_chain: Option<String>,
    pub source_offset: i64,
    pub source_partition: i32,
}

impl CohortStreamEvent {
    /// Moves every owned field out of `event` rather than cloning; `person_id` is extracted
    /// upstream and passed in separately.
    pub fn from_clickhouse(
        event: ClickHouseEvent,
        person_id: String,
        source_partition: i32,
        source_offset: i64,
    ) -> Self {
        Self {
            team_id: event.team_id,
            person_id,
            distinct_id: event.distinct_id,
            uuid: event.uuid.to_string(),
            event: event.event,
            timestamp: event.timestamp,
            properties: event.properties,
            person_properties: event.person_properties,
            elements_chain: event.elements_chain,
            source_offset,
            source_partition,
        }
    }

    pub fn partition_key(&self) -> String {
        partition_key(self.team_id, &self.person_id)
    }
}

#[cfg(test)]
pub(crate) fn sample_clickhouse_event(team_id: i32, person_id: Option<&str>) -> ClickHouseEvent {
    use common_types::PersonMode;
    use uuid::Uuid;

    ClickHouseEvent {
        uuid: Uuid::from_u128(0x0192_8aaa_bbbb_cccc_dddd_eeee_eeee_eeee),
        team_id,
        project_id: Some(7),
        event: "$pageview".to_string(),
        distinct_id: "user@example.com".to_string(),
        properties: Some(r#"{"$current_url":"/pricing"}"#.to_string()),
        person_id: person_id.map(str::to_string),
        timestamp: "2026-05-26 12:34:56.789000".to_string(),
        created_at: "2026-05-26 12:34:57.000000".to_string(),
        captured_at: None,
        elements_chain: Some("a:href=\"/x\"".to_string()),
        person_created_at: None,
        person_properties: Some(r#"{"email":"u@p.com"}"#.to_string()),
        group0_properties: Some("{}".to_string()),
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

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_event(team_id: i32, person_id: Option<&str>) -> ClickHouseEvent {
        sample_clickhouse_event(team_id, person_id)
    }

    #[test]
    fn partition_key_is_team_colon_person() {
        assert_eq!(partition_key(42, "abc"), "42:abc");
        assert_eq!(partition_key(-1, ""), "-1:");
    }

    #[test]
    fn partition_key_is_deterministic_across_calls() {
        let a = partition_key(2, "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        let b = partition_key(2, "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        assert_eq!(a, b);
    }

    #[test]
    fn from_clickhouse_maps_every_field() {
        let event = sample_event(42, Some("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee"));
        // from_clickhouse consumes the event, so capture the uuid first.
        let expected_uuid = event.uuid.to_string();
        let envelope = CohortStreamEvent::from_clickhouse(
            event,
            "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
            17,
            12345,
        );

        assert_eq!(envelope.team_id, 42);
        assert_eq!(envelope.person_id, "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        assert_eq!(envelope.distinct_id, "user@example.com");
        assert_eq!(envelope.uuid, expected_uuid);
        assert_eq!(envelope.event, "$pageview");
        assert_eq!(envelope.timestamp, "2026-05-26 12:34:56.789000");
        assert_eq!(
            envelope.properties.as_deref(),
            Some(r#"{"$current_url":"/pricing"}"#)
        );
        assert_eq!(
            envelope.person_properties.as_deref(),
            Some(r#"{"email":"u@p.com"}"#)
        );
        assert_eq!(envelope.elements_chain.as_deref(), Some("a:href=\"/x\""));
        assert_eq!(envelope.source_partition, 17);
        assert_eq!(envelope.source_offset, 12345);
    }

    #[test]
    fn from_clickhouse_preserves_null_optionals() {
        let mut event = sample_event(1, Some("p"));
        event.properties = None;
        event.person_properties = None;
        event.elements_chain = None;

        let envelope = CohortStreamEvent::from_clickhouse(event, "p".to_string(), 0, 0);
        assert!(envelope.properties.is_none());
        assert!(envelope.person_properties.is_none());
        assert!(envelope.elements_chain.is_none());
    }

    #[test]
    fn envelope_partition_key_matches_free_function() {
        let event = sample_event(99, Some("xyz"));
        let envelope = CohortStreamEvent::from_clickhouse(event, "xyz".to_string(), 3, 9);
        assert_eq!(envelope.partition_key(), "99:xyz");
        assert_eq!(envelope.partition_key(), partition_key(99, "xyz"));
    }

    #[test]
    fn serialized_envelope_has_tdd_4_3_keys() {
        let event = sample_event(42, Some("p1"));
        let envelope = CohortStreamEvent::from_clickhouse(event, "p1".to_string(), 17, 12345);
        let value: serde_json::Value = serde_json::to_value(&envelope).unwrap();
        let obj = value.as_object().unwrap();

        for key in [
            "team_id",
            "person_id",
            "distinct_id",
            "uuid",
            "event",
            "timestamp",
            "properties",
            "person_properties",
            "elements_chain",
            "source_offset",
            "source_partition",
        ] {
            assert!(obj.contains_key(key), "envelope is missing key `{key}`");
        }
        // Replay coordinates must serialize numeric, not as strings.
        assert_eq!(obj["source_offset"], serde_json::json!(12345));
        assert_eq!(obj["source_partition"], serde_json::json!(17));
    }

    #[test]
    fn envelope_round_trips_through_json() {
        let event = sample_event(42, Some("p1"));
        let envelope = CohortStreamEvent::from_clickhouse(event, "p1".to_string(), 17, 12345);
        let json = serde_json::to_string(&envelope).unwrap();
        let decoded: CohortStreamEvent = serde_json::from_str(&json).unwrap();
        assert_eq!(envelope, decoded);
    }
}
