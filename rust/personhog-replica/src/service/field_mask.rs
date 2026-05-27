use std::collections::HashSet;

use personhog_proto::personhog::types::v1::{Group, Person, ReadOptions};

const PERSON_PROPERTIES_FIELDS: &[&str] =
    &["properties", "properties_last_updated_at", "properties_last_operation"];

const GROUP_PROPERTIES_FIELDS: &[&str] = &[
    "group_properties",
    "properties_last_updated_at",
    "properties_last_operation",
];

/// Returns true if the field mask requires properties columns from the database.
/// An empty mask means "all fields" and requires properties.
pub fn needs_properties(read_options: &Option<ReadOptions>, property_fields: &[&str]) -> bool {
    let mask = match read_options.as_ref() {
        Some(opts) if !opts.field_mask.is_empty() => &opts.field_mask,
        _ => return true,
    };
    mask.iter().any(|f| property_fields.contains(&f.as_str()))
}

/// Returns true if the field mask requires person properties columns.
pub fn person_needs_properties(read_options: &Option<ReadOptions>) -> bool {
    needs_properties(read_options, PERSON_PROPERTIES_FIELDS)
}

/// Returns true if the field mask requires group properties columns.
pub fn group_needs_properties(read_options: &Option<ReadOptions>) -> bool {
    needs_properties(read_options, GROUP_PROPERTIES_FIELDS)
}

/// Build a field mask set from read options. Returns None if all fields should be kept.
pub fn build_field_mask(read_options: &Option<ReadOptions>) -> Option<HashSet<String>> {
    match read_options.as_ref() {
        Some(opts) if !opts.field_mask.is_empty() => {
            Some(opts.field_mask.iter().cloned().collect())
        }
        _ => None,
    }
}

/// Apply the field mask to a Person proto, zeroing out fields not in the mask.
/// If the mask is None, all fields are kept.
pub fn apply_person_field_mask(person: &mut Person, fields: &Option<HashSet<String>>) {
    let fields = match fields {
        Some(f) => f,
        None => return,
    };

    if !fields.contains("id") {
        person.id = 0;
    }
    if !fields.contains("uuid") {
        person.uuid.clear();
    }
    if !fields.contains("team_id") {
        person.team_id = 0;
    }
    if !fields.contains("properties") {
        person.properties.clear();
    }
    if !fields.contains("properties_last_updated_at") {
        person.properties_last_updated_at.clear();
    }
    if !fields.contains("properties_last_operation") {
        person.properties_last_operation.clear();
    }
    if !fields.contains("created_at") {
        person.created_at = 0;
    }
    if !fields.contains("version") {
        person.version = 0;
    }
    if !fields.contains("is_identified") {
        person.is_identified = false;
    }
    if !fields.contains("is_user_id") {
        person.is_user_id = None;
    }
    if !fields.contains("last_seen_at") {
        person.last_seen_at = None;
    }
}

/// Apply the field mask to a Group proto, zeroing out fields not in the mask.
/// If the mask is None, all fields are kept.
pub fn apply_group_field_mask(group: &mut Group, fields: &Option<HashSet<String>>) {
    let fields = match fields {
        Some(f) => f,
        None => return,
    };

    if !fields.contains("id") {
        group.id = 0;
    }
    if !fields.contains("team_id") {
        group.team_id = 0;
    }
    if !fields.contains("group_type_index") {
        group.group_type_index = 0;
    }
    if !fields.contains("group_key") {
        group.group_key.clear();
    }
    if !fields.contains("group_properties") {
        group.group_properties.clear();
    }
    if !fields.contains("properties_last_updated_at") {
        group.properties_last_updated_at.clear();
    }
    if !fields.contains("properties_last_operation") {
        group.properties_last_operation.clear();
    }
    if !fields.contains("created_at") {
        group.created_at = 0;
    }
    if !fields.contains("version") {
        group.version = 0;
    }
}
