//! Shared person-storage primitives used by the personhog services that read
//! or write person rows in Postgres (replica, identity). Each service keeps
//! its own SQL; the row type and deterministic UUID scheme live here so the
//! services cannot drift apart. Error classification lives in
//! [`crate::storage_error`].

use uuid::Uuid;

/// Namespace for deterministic person UUIDs (uuidv5 of "team_id:distinct_id").
/// Mirrors the Django/plugin-server convention.
pub const PERSON_UUIDV5_NAMESPACE: Uuid = Uuid::from_bytes([
    0x93, 0x29, 0x79, 0xb4, 0x65, 0xc3, 0x44, 0x24, 0x84, 0x67, 0x0b, 0x66, 0xec, 0x27, 0xbc, 0x22,
]);

/// The deterministic person UUID for a (team_id, distinct_id) pair.
pub fn person_uuid(team_id: i64, distinct_id: &str) -> Uuid {
    Uuid::new_v5(
        &PERSON_UUIDV5_NAMESPACE,
        format!("{team_id}:{distinct_id}").as_bytes(),
    )
}

#[derive(Debug, Clone)]
pub struct Person {
    pub id: i64,
    pub uuid: Uuid,
    pub team_id: i64,
    pub properties: Option<String>,
    pub properties_last_updated_at: Option<String>,
    pub properties_last_operation: Option<String>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub version: Option<i64>,
    pub is_identified: bool,
    pub is_user_id: Option<bool>,
    pub last_seen_at: Option<chrono::DateTime<chrono::Utc>>,
}

impl From<Person> for personhog_proto::personhog::types::v1::Person {
    fn from(person: Person) -> Self {
        personhog_proto::personhog::types::v1::Person {
            id: person.id,
            uuid: person.uuid.to_string(),
            team_id: person.team_id,
            properties: person
                .properties
                .map(|v| v.into_bytes())
                .unwrap_or_default(),
            properties_last_updated_at: person
                .properties_last_updated_at
                .map(|v| v.into_bytes())
                .unwrap_or_default(),
            properties_last_operation: person
                .properties_last_operation
                .map(|v| v.into_bytes())
                .unwrap_or_default(),
            created_at: person.created_at.timestamp_millis(),
            version: person.version.unwrap_or(0),
            is_identified: person.is_identified,
            is_user_id: person.is_user_id,
            last_seen_at: person.last_seen_at.map(|t| t.timestamp_millis()),
        }
    }
}
