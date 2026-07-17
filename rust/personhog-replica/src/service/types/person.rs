use personhog_proto::personhog::types::v1::Person;

use crate::storage;

impl From<storage::Person> for Person {
    fn from(person: storage::Person) -> Self {
        Person {
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
            // Changelog-only field (see the proto comment); never set in
            // read responses.
            initial_distinct_ids: vec![],
        }
    }
}
