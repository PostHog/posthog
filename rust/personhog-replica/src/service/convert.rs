use personhog_proto::personhog::types::v1::{Group, GroupTypeMapping, Person};
use tonic::Status;
use tracing::error;

use crate::storage;

pub fn person_to_proto(person: storage::Person) -> Person {
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

pub fn group_to_proto(group: storage::Group) -> Group {
    Group {
        id: group.id,
        team_id: group.team_id,
        group_type_index: group.group_type_index,
        group_key: group.group_key,
        group_properties: serde_json::to_vec(&group.group_properties).unwrap_or_default(),
        created_at: group.created_at.timestamp_millis(),
        properties_last_updated_at: group
            .properties_last_updated_at
            .map(|v| serde_json::to_vec(&v).unwrap_or_default())
            .unwrap_or_default(),
        properties_last_operation: group
            .properties_last_operation
            .map(|v| serde_json::to_vec(&v).unwrap_or_default())
            .unwrap_or_default(),
        version: group.version,
    }
}

pub fn group_type_mapping_to_proto(mapping: storage::GroupTypeMapping) -> GroupTypeMapping {
    GroupTypeMapping {
        id: mapping.id,
        team_id: mapping.team_id,
        project_id: mapping.project_id,
        group_type: mapping.group_type,
        group_type_index: mapping.group_type_index,
        name_singular: mapping.name_singular,
        name_plural: mapping.name_plural,
        default_columns: mapping
            .default_columns
            .map(|v| serde_json::to_vec(&v).unwrap_or_default()),
        detail_dashboard_id: mapping.detail_dashboard_id,
        created_at: mapping.created_at.map(|t| t.timestamp_millis()),
    }
}

pub fn log_and_convert_error(err: storage::StorageError, operation: &str) -> Status {
    let status = match &err {
        // Connection/pool errors are transient - signal client to retry
        storage::StorageError::Connection(msg) => {
            error!(operation, error = %msg, "Database connection error");
            Status::unavailable(format!("Database unavailable: {msg}"))
        }
        storage::StorageError::PoolExhausted => {
            error!(operation, "Database pool exhausted");
            Status::unavailable("Database pool exhausted")
        }
        // Query errors are internal server errors
        storage::StorageError::Query(msg) => {
            error!(operation, error = %msg, "Database query error");
            Status::internal(format!("Database error: {msg}"))
        }
    };
    status
}
