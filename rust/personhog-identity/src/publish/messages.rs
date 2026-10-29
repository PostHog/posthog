//! Wire payloads the publisher produces. Field names and types are the
//! Node ingestion worker's, byte for byte: the ClickHouse Kafka engine
//! table, `flags-consumer`, the hogflow subscription matcher and the cohort
//! stream processor all decode the same topics whichever path produced the
//! message.

use serde::Serialize;
use uuid::Uuid;

/// One `clickhouse_person_distinct_id` row. `person_id` is the owning
/// person's uuid (ClickHouse never sees Postgres person ids), and
/// `is_deleted` is a 0 or 1 integer rather than a boolean because the Kafka
/// table column is `Int8`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DistinctIdRow {
    pub person_id: Uuid,
    pub team_id: i64,
    pub distinct_id: String,
    pub version: i64,
    pub is_deleted: u8,
}

/// Mirrors `MERGE_EVENT_SCHEMA_VERSION` in the cohort stream processor.
pub const MERGE_EVENT_SCHEMA_VERSION: u32 = 1;

/// One `person_merge_events` message: the committed merge of
/// `old_person_uuid` into `new_person_uuid`. The cohort stream processor
/// reads `team_id` as i32, `merged_at_ms` as i64 and `schema_version` as
/// u32, so each has to serialize as a JSON number. It is produced under
/// [`PersonMergeEvent::key`]; the partitioner that places the key is
/// pinned by [`crate::publish::config::MURMUR2_RANDOM`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PersonMergeEvent {
    pub team_id: i32,
    pub old_person_uuid: Uuid,
    pub new_person_uuid: Uuid,
    pub merged_at_ms: i64,
    pub schema_version: u32,
}

impl PersonMergeEvent {
    /// Node's key, `"{team_id}:{old_person_uuid}"`: the old person, because
    /// its state is what the merge moves.
    pub fn key(&self) -> String {
        format!("{}:{}", self.team_id, self.old_person_uuid)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // The consumers decode by field name; a rename or a boolean `is_deleted`
    // would be dropped by the ClickHouse Kafka table without an error.
    #[test]
    fn distinct_id_row_serializes_exactly_as_the_node_producer_does() {
        let row = DistinctIdRow {
            person_id: Uuid::parse_str("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee").unwrap(),
            team_id: 2,
            distinct_id: "user-1".to_string(),
            version: 3,
            is_deleted: 1,
        };
        assert_eq!(
            serde_json::to_string(&row).unwrap(),
            r#"{"person_id":"01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee","team_id":2,"distinct_id":"user-1","version":3,"is_deleted":1}"#
        );
    }

    #[test]
    fn merge_event_serializes_and_keys_exactly_as_the_node_producer_does() {
        let event = PersonMergeEvent {
            team_id: 2,
            old_person_uuid: Uuid::parse_str("01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee").unwrap(),
            new_person_uuid: Uuid::parse_str("01928bbb-cccc-dddd-eeee-ffffffffffff").unwrap(),
            merged_at_ms: 1_700_000_000_000,
            schema_version: MERGE_EVENT_SCHEMA_VERSION,
        };
        assert_eq!(event.key(), "2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        assert_eq!(
            serde_json::to_string(&event).unwrap(),
            r#"{"team_id":2,"old_person_uuid":"01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee","new_person_uuid":"01928bbb-cccc-dddd-eeee-ffffffffffff","merged_at_ms":1700000000000,"schema_version":1}"#
        );
    }
}
