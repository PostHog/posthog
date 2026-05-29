//! The `cohort_stream_events` envelope (TDD §4.3) and the canonical re-key derivation.
//!
//! The shuffler forwards a *thin* copy of each [`ClickHouseEvent`] — only the fields Stage 1's
//! bytecode evaluation needs — keyed by [`partition_key`]. Group properties, `person_mode`,
//! `created_at`, `project_id` and similar are intentionally dropped (TDD §2.2).

use common_types::ClickHouseEvent;
use serde::{Deserialize, Serialize};

/// The single source of truth for the `cohort_stream_events` re-key string.
///
/// Every producer that targets a topic co-partitioned with `cohort_stream_events`
/// (the future seed, merge, and cascade producers — TDD §4.4/§4.5/§4.8) **must** derive
/// its key with this function. Combined with the `murmur2_random` partitioner and a fixed
/// 64-partition count, this is what guarantees that a given `(team_id, person_id)` always
/// lands on the same partition — and therefore the same Stage 1 worker — across topics and
/// across runtimes (Rust here, Node for `person_merge_events`). See key design point 1.
#[inline]
pub fn partition_key(team_id: i32, person_id: &str) -> String {
    format!("{team_id}:{person_id}")
}

/// The re-keying envelope published to `cohort_stream_events`.
///
/// Field names mirror TDD §4.3 exactly so the Stage 1 consumer (PR 1.7) can deserialize a
/// matching struct. `source_partition` / `source_offset` carry the upstream
/// `clickhouse_events_json` coordinates so Stage 1 can make non-idempotent counter
/// increments replay-safe via per-key offset tracking (TDD §2.5, key design point 2).
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
    /// Build the forwarded envelope from a source event and its Kafka coordinates.
    ///
    /// Infallible: [`crate::consumer::classify`] has already proved the event carries a
    /// `person_id` and moved it out, handing it back here — so there is no `Option` to re-check.
    /// Takes `event` by value and *moves* every owned field out of it; the caller drops the
    /// source event immediately after, so the bytes — including the unbounded `properties` /
    /// `person_properties` JSON payloads — are moved rather than cloned.
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

    /// The Kafka message key for this envelope: [`partition_key`] over its own
    /// `(team_id, person_id)`.
    pub fn partition_key(&self) -> String {
        partition_key(self.team_id, &self.person_id)
    }
}

/// Shared test fixture: a fully-populated `ClickHouseEvent` for the given team and
/// (optional) person. Used by both this module's tests and the consumer's tests.
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
        // from_clickhouse consumes the event, so capture the uuid string first.
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
        // The replay-idempotence coordinates must be numeric, not strings.
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
