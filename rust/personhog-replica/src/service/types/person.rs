use personhog_proto::personhog::types::v1::Person;

use crate::storage;

impl From<storage::Person> for Person {
    fn from(person: storage::Person) -> Self {
        Person {
            id: person.id,
            uuid: person.uuid.to_string(),
            team_id: person.team_id,
            properties: serde_json::to_vec(&person.properties).unwrap_or_default(),
            properties_last_updated_at: person
                .properties_last_updated_at
                .map(|v| serde_json::to_vec(&v).unwrap_or_default())
                .unwrap_or_default(),
            properties_last_operation: person
                .properties_last_operation
                .map(|v| serde_json::to_vec(&v).unwrap_or_default())
                .unwrap_or_default(),
            created_at: person.created_at.timestamp_millis(),
            version: person.version.unwrap_or(0),
            is_identified: person.is_identified,
            is_user_id: person.is_user_id.unwrap_or(false),
        }
    }
}
