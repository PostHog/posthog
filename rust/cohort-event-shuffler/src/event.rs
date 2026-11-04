//! The `cohort_stream_events` envelope and the canonical re-key derivation.
//!
//! Forwards only the fields the downstream bytecode evaluation needs; group properties,
//! `created_at`, `project_id` and similar are intentionally dropped. `person_mode` is consumed, not
//! forwarded: it decides whether `person_properties` is the person's properties or a placeholder.

#[cfg(test)]
use common_types::ClickHouseEvent;
use common_types::PersonMode;
use serde::{de, Deserialize, Deserializer, Serialize};
use serde_json::value::RawValue;
use uuid::Uuid;

use crate::ledger::SourcePartition;

/// Single source of truth for the re-key string. Every producer targeting a topic co-partitioned
/// with `cohort_stream_events` must use this so a given `(team_id, person_id)` lands on the same
/// partition — and downstream worker — across topics and runtimes (Rust here, Node for
/// `person_merge_events`), given the shared `murmur2_random` partitioner and 64-partition count.
#[inline]
pub fn partition_key(team_id: i32, person_id: &str) -> String {
    format!("{team_id}:{person_id}")
}

/// Each input topic's slot in the `source_partition` numbers of `cohort_stream_events`. Kafka
/// numbers every topic's partitions from 0. The processor keys its replay marks by
/// `source_partition` alone, so two topics that shared numbers would mask each other's lower offsets
/// as replays. A slot must never pass to another topic, because stored replay marks keep the numbers
/// that the first topic wrote.
const INPUT_TOPIC_SLOTS: [(&str, u8); 2] = [
    ("clickhouse_events_json", 0),
    ("realtime_only_events_json", 1),
];

#[derive(Debug, Clone, Copy)]
pub struct SourcePartitionRange {
    slot: u8,
}

impl SourcePartitionRange {
    const STRIDE: i32 = 1_000_000;

    pub fn for_input_topic(input_topic: &str) -> Option<Self> {
        INPUT_TOPIC_SLOTS
            .iter()
            .find(|(topic, _)| *topic == input_topic)
            .map(|&(_, slot)| Self { slot })
    }

    /// The envelope's `source_partition` for `input_partition`. `None` for a partition outside
    /// `0..1_000_000`, whose number would fall in another slot's range.
    pub fn envelope_partition(self, input_partition: SourcePartition) -> Option<i32> {
        (0..Self::STRIDE)
            .contains(&input_partition.0)
            .then(|| i32::from(self.slot) * Self::STRIDE + input_partition.0)
    }
}

/// A JSON string token, quotes and escapes included, exactly as the firehose spelled it. The
/// shuffler never reads the blobs it forwards, so it copies them instead of unescaping and
/// re-escaping them. The processor's `Option<String>` decode reads the same string from either
/// spelling. serde_json's capture does not check that `\u` surrogate escapes pair up, so a token
/// with a lone surrogate reaches the processor, which then rejects the whole envelope as an
/// undeserializable message.
#[derive(Debug, Clone, Serialize)]
#[serde(transparent)]
pub struct RawJsonString(Box<RawValue>);

impl RawJsonString {
    pub fn get(&self) -> &str {
        self.0.get()
    }
}

impl<'de> Deserialize<'de> for RawJsonString {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = Box::<RawValue>::deserialize(deserializer)?;
        // serde_json skips the whitespace before a value it captures, so only a string token
        // starts with a quote.
        if raw.get().starts_with('"') {
            Ok(Self(raw))
        } else {
            Err(de::Error::custom("expected a JSON string"))
        }
    }
}

impl PartialEq for RawJsonString {
    fn eq(&self, other: &Self) -> bool {
        self.get() == other.get()
    }
}

impl Eq for RawJsonString {}

/// The fields of a firehose event that the envelope forwards, parsed only for gate survivors. The
/// other fields stay undeclared, so serde skips them without allocating.
#[derive(Debug, Deserialize)]
pub(crate) struct ForwardFields {
    pub(crate) uuid: Uuid,
    pub(crate) team_id: i32,
    pub(crate) event: String,
    pub(crate) distinct_id: String,
    pub(crate) person_id: String,
    pub(crate) timestamp: String,
    pub(crate) properties: Option<RawJsonString>,
    pub(crate) person_properties: Option<RawJsonString>,
    pub(crate) elements_chain: Option<RawJsonString>,
    pub(crate) person_mode: PersonMode,
}

/// `source_partition` / `source_offset` carry the upstream coordinates, numbered by
/// [`SourcePartitionRange`], so the downstream processor can make counter increments replay-safe.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CohortStreamEvent {
    pub team_id: i32,
    pub person_id: String,
    pub distinct_id: String,
    pub uuid: String,
    pub event: String,
    pub timestamp: String,
    pub properties: Option<RawJsonString>,
    pub person_properties: Option<RawJsonString>,
    pub elements_chain: Option<RawJsonString>,
    pub source_offset: i64,
    pub source_partition: i32,
}

/// The label of a `person_mode` under which ingestion processed the event without a person profile.
/// Such an event carries the real `person_id` but `{}` as `person_properties`, and the processor
/// cannot tell that placeholder from a person who has no properties. `None` for `full`, the only
/// mode under which ingestion attaches the person's properties to the event.
pub(crate) fn personless_mode(mode: PersonMode) -> Option<&'static str> {
    match mode {
        PersonMode::Full => None,
        PersonMode::Propertyless => Some("propertyless"),
        PersonMode::ForceUpgrade => Some("force_upgrade"),
    }
}

impl CohortStreamEvent {
    /// Moves every field out of `fields` rather than cloning. A personless event forwards
    /// `person_properties` as null, so the processor leaves the person's record alone and still
    /// counts the event for behavioral conditions.
    pub(crate) fn from_forward(
        fields: ForwardFields,
        source_partition: i32,
        source_offset: i64,
    ) -> Self {
        let ForwardFields {
            uuid,
            team_id,
            event,
            distinct_id,
            person_id,
            timestamp,
            properties,
            person_properties,
            elements_chain,
            person_mode,
        } = fields;
        Self {
            team_id,
            person_id,
            distinct_id,
            uuid: uuid.to_string(),
            event,
            timestamp,
            properties,
            person_properties: person_properties.filter(|_| personless_mode(person_mode).is_none()),
            elements_chain,
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

    /// The firehose message for `event`, parsed as the survivor path parses it.
    fn forward_fields(event: &ClickHouseEvent) -> ForwardFields {
        serde_json::from_slice(&serde_json::to_vec(event).unwrap()).unwrap()
    }

    /// The string the processor's `Option<String>` decode reads from a forwarded blob.
    fn decoded(blob: Option<&RawJsonString>) -> Option<String> {
        blob.map(|raw| serde_json::from_str(raw.get()).unwrap())
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
    fn each_input_topic_writes_its_partitions_into_its_own_range() {
        for (topic, partition, expected) in [
            ("clickhouse_events_json", 5, Some(5)),
            ("clickhouse_events_json", 1_000_005, None),
            ("realtime_only_events_json", 5, Some(1_000_005)),
            ("realtime_only_events_json", 1_000_000, None),
        ] {
            let range = SourcePartitionRange::for_input_topic(topic).unwrap();
            assert_eq!(
                range.envelope_partition(SourcePartition(partition)),
                expected,
                "{topic} partition {partition}"
            );
        }
    }

    #[test]
    fn no_two_input_topics_share_a_slot_and_no_topic_has_two() {
        let slots: std::collections::BTreeSet<u8> =
            INPUT_TOPIC_SLOTS.iter().map(|&(_, slot)| slot).collect();
        assert_eq!(
            slots.len(),
            INPUT_TOPIC_SLOTS.len(),
            "two topics share a slot, so the processor would drop one topic's events as replays"
        );
        let topics: std::collections::BTreeSet<&str> =
            INPUT_TOPIC_SLOTS.iter().map(|&(topic, _)| topic).collect();
        assert_eq!(
            topics.len(),
            INPUT_TOPIC_SLOTS.len(),
            "a topic has two rows, and the shuffler uses only the first"
        );
    }

    #[test]
    fn from_forward_maps_every_field() {
        let event = sample_event(42, Some("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee"));
        let envelope = CohortStreamEvent::from_forward(forward_fields(&event), 17, 12345);

        assert_eq!(envelope.team_id, 42);
        assert_eq!(envelope.person_id, "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        assert_eq!(envelope.distinct_id, "user@example.com");
        assert_eq!(envelope.uuid, event.uuid.to_string());
        assert_eq!(envelope.event, "$pageview");
        assert_eq!(envelope.timestamp, "2026-05-26 12:34:56.789000");
        assert_eq!(
            decoded(envelope.properties.as_ref()).as_deref(),
            Some(r#"{"$current_url":"/pricing"}"#)
        );
        assert_eq!(
            decoded(envelope.person_properties.as_ref()).as_deref(),
            Some(r#"{"email":"u@p.com"}"#)
        );
        assert_eq!(
            decoded(envelope.elements_chain.as_ref()).as_deref(),
            Some("a:href=\"/x\"")
        );
        assert_eq!(envelope.source_partition, 17);
        assert_eq!(envelope.source_offset, 12345);
    }

    #[test]
    fn from_forward_preserves_null_optionals() {
        let mut event = sample_event(1, Some("p"));
        event.properties = None;
        event.person_properties = None;
        event.elements_chain = None;

        let envelope = CohortStreamEvent::from_forward(forward_fields(&event), 0, 0);
        assert!(envelope.properties.is_none());
        assert!(envelope.person_properties.is_none());
        assert!(envelope.elements_chain.is_none());
    }

    #[test]
    fn from_forward_forwards_a_person_payload_only_for_a_full_event() {
        let envelope = |person_mode| {
            let event = ClickHouseEvent {
                person_mode,
                person_properties: Some("{}".to_string()),
                ..sample_event(2, Some("p"))
            };
            CohortStreamEvent::from_forward(forward_fields(&event), 0, 0)
        };

        let full = envelope(PersonMode::Full);
        assert_eq!(
            decoded(full.person_properties.as_ref()).as_deref(),
            Some("{}"),
            "a full event with no person properties still describes the person"
        );
        for mode in [PersonMode::Propertyless, PersonMode::ForceUpgrade] {
            assert_eq!(
                envelope(mode),
                CohortStreamEvent {
                    person_properties: None,
                    ..full.clone()
                },
                "a {mode:?} event drops only its person payload"
            );
        }
    }

    #[test]
    fn envelope_partition_key_matches_free_function() {
        let event = sample_event(99, Some("xyz"));
        let envelope = CohortStreamEvent::from_forward(forward_fields(&event), 3, 9);
        assert_eq!(envelope.partition_key(), "99:xyz");
        assert_eq!(envelope.partition_key(), partition_key(99, "xyz"));
    }

    #[test]
    fn forwarded_blobs_keep_the_firehose_spelling() {
        // A decode and re-encode would respell each of these escapes: `\u00e3` as `ã`, `\/` as
        // `/`, `\u000a` as `\n`.
        let properties = r#""{\"city\":\"S\u00e3o Paulo\"}""#;
        let person_properties = r#""{\"home\":\"https:\/\/example.com\"}""#;
        let elements_chain = r#""a:href=\"\/x\"\u000a""#;
        let payload = format!(
            r#"{{"uuid": "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee", "team_id": 2,
                "event": "$pageview", "distinct_id": "d", "person_id": "p",
                "timestamp": "2026-05-26 12:34:56.789000", "person_mode": "full",
                "properties": {properties}, "person_properties": {person_properties},
                "elements_chain": {elements_chain}}}"#
        );

        let fields: ForwardFields = serde_json::from_str(&payload).unwrap();
        let envelope =
            serde_json::to_string(&CohortStreamEvent::from_forward(fields, 0, 0)).unwrap();

        for (key, raw) in [
            ("properties", properties),
            ("person_properties", person_properties),
            ("elements_chain", elements_chain),
        ] {
            assert!(
                envelope.contains(&format!(r#""{key}":{raw}"#)),
                "`{key}` was respelled in {envelope}"
            );
        }
        let processor_view: serde_json::Value = serde_json::from_str(&envelope).unwrap();
        assert_eq!(processor_view["properties"], r#"{"city":"São Paulo"}"#);
        assert_eq!(
            processor_view["person_properties"],
            r#"{"home":"https://example.com"}"#
        );
        assert_eq!(processor_view["elements_chain"], "a:href=\"/x\"\n");
    }

    #[test]
    fn serialized_envelope_has_tdd_4_3_keys() {
        let event = sample_event(42, Some("p1"));
        let envelope = CohortStreamEvent::from_forward(forward_fields(&event), 17, 12345);
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
        let envelope = CohortStreamEvent::from_forward(forward_fields(&event), 17, 12345);
        let json = serde_json::to_string(&envelope).unwrap();
        let decoded: CohortStreamEvent = serde_json::from_str(&json).unwrap();
        assert_eq!(envelope, decoded);
    }
}
