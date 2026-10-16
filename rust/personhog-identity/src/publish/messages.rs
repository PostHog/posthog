//! Wire payloads the publisher produces. Field names and types are the
//! Node ingestion worker's, byte for byte: the ClickHouse Kafka engine
//! table, `flags-consumer` and the hogflow subscription matcher all decode
//! the same topic whichever path produced the row.

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
}
