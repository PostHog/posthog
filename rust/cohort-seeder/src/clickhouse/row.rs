//! ClickHouse row decoding: the scanned event columns and their lift into a `CohortStreamEvent`.
//! Depends on `cohort-core`; never on `store` or `domain`.

use clickhouse::Row;
use cohort_core::events::CohortStreamEvent;
use cohort_core::filters::TeamId;
use serde::Deserialize;

#[derive(Debug, Row, Deserialize, PartialEq, Eq)]
pub struct EventRow {
    pub uuid: String,
    pub event: String,
    pub properties: String,
    pub timestamp: String,
    pub distinct_id: String,
    pub person_id: String,
    pub person_properties: String,
    pub elements_chain: String,
}

pub fn row_to_event(team_id: TeamId, row: EventRow) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: team_id.0,
        person_id: row.person_id,
        distinct_id: row.distinct_id,
        uuid: row.uuid,
        event: row.event,
        timestamp: row.timestamp,
        properties: non_empty(row.properties),
        person_properties: non_empty(row.person_properties),
        elements_chain: non_empty(row.elements_chain),
        source_offset: 0,
        source_partition: -1,
        redirected_from: None,
        redirect_hops: 0,
    }
}

fn non_empty(value: String) -> Option<String> {
    (!value.is_empty()).then_some(value)
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;

    fn row(timestamp: &str) -> EventRow {
        EventRow {
            uuid: Uuid::from_u128(1).to_string(),
            event: "purchase".to_string(),
            properties: "{}".to_string(),
            timestamp: timestamp.to_string(),
            distinct_id: "distinct".to_string(),
            person_id: Uuid::from_u128(2).to_string(),
            person_properties: "{}".to_string(),
            elements_chain: String::new(),
        }
    }

    #[test]
    fn row_conversion_restores_optional_fields_and_seed_sentinels() {
        let event = row_to_event(
            TeamId(2),
            EventRow {
                properties: String::new(),
                person_properties: "{\"plan\":\"paid\"}".to_string(),
                elements_chain: String::new(),
                ..row("1970-01-02 12:00:00.000000")
            },
        );
        assert_eq!(event.team_id, 2);
        assert_eq!(event.properties, None);
        assert_eq!(
            event.person_properties.as_deref(),
            Some("{\"plan\":\"paid\"}")
        );
        assert_eq!(event.elements_chain, None);
        assert_eq!(event.source_partition, -1);
        assert_eq!(event.source_offset, 0);
    }
}
