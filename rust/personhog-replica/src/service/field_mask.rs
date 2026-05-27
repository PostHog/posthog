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

#[cfg(test)]
mod tests {
    use super::*;

    fn read_options_with_mask(fields: Vec<&str>) -> Option<ReadOptions> {
        Some(ReadOptions {
            consistency: 0,
            field_mask: fields.into_iter().map(String::from).collect(),
        })
    }

    fn populated_person() -> Person {
        Person {
            id: 42,
            uuid: "some-uuid".to_string(),
            team_id: 7,
            properties: b"{}".to_vec(),
            properties_last_updated_at: b"ts".to_vec(),
            properties_last_operation: b"op".to_vec(),
            created_at: 1000,
            version: 3,
            is_identified: true,
            is_user_id: Some(false),
            last_seen_at: Some(9999),
        }
    }

    fn populated_group() -> Group {
        Group {
            id: 10,
            team_id: 5,
            group_type_index: 2,
            group_key: "acme".to_string(),
            group_properties: b"{\"k\":\"v\"}".to_vec(),
            properties_last_updated_at: b"ts".to_vec(),
            properties_last_operation: b"op".to_vec(),
            created_at: 2000,
            version: 1,
        }
    }

    // ============================================================
    // build_field_mask
    // ============================================================

    #[test]
    fn build_field_mask_returns_none_when_read_options_is_none() {
        let result = build_field_mask(&None);
        assert!(result.is_none());
    }

    #[test]
    fn build_field_mask_returns_none_when_field_mask_is_empty() {
        let result = build_field_mask(&read_options_with_mask(vec![]));
        assert!(result.is_none());
    }

    #[test]
    fn build_field_mask_returns_set_of_requested_fields() {
        let result = build_field_mask(&read_options_with_mask(vec!["id", "uuid", "team_id"]));
        let set = result.expect("should return Some");
        assert_eq!(set.len(), 3);
        assert!(set.contains("id"));
        assert!(set.contains("uuid"));
        assert!(set.contains("team_id"));
    }

    #[test]
    fn build_field_mask_deduplicates_repeated_fields() {
        let result = build_field_mask(&read_options_with_mask(vec!["id", "id", "uuid"]));
        let set = result.expect("should return Some");
        assert_eq!(set.len(), 2);
    }

    // ============================================================
    // needs_properties / person_needs_properties / group_needs_properties
    // ============================================================

    use rstest::rstest;

    #[rstest]
    #[case::no_read_options(None, true)]
    #[case::empty_mask(Some(vec![]), true)]
    #[case::mask_includes_properties(Some(vec!["properties"]), true)]
    #[case::mask_includes_properties_last_updated_at(Some(vec!["properties_last_updated_at"]), true)]
    #[case::mask_includes_properties_last_operation(Some(vec!["properties_last_operation"]), true)]
    #[case::mask_with_only_non_property_fields(Some(vec!["id", "uuid"]), false)]
    fn person_needs_properties_reflects_whether_mask_requests_property_fields(
        #[case] mask_fields: Option<Vec<&str>>,
        #[case] expected: bool,
    ) {
        let read_options = mask_fields.map(read_options_with_mask).flatten();
        assert_eq!(person_needs_properties(&read_options), expected);
    }

    #[rstest]
    #[case::no_read_options(None, true)]
    #[case::empty_mask(Some(vec![]), true)]
    #[case::mask_includes_group_properties(Some(vec!["group_properties"]), true)]
    #[case::mask_includes_properties_last_updated_at(Some(vec!["properties_last_updated_at"]), true)]
    #[case::mask_includes_properties_last_operation(Some(vec!["properties_last_operation"]), true)]
    #[case::mask_with_only_non_property_fields(Some(vec!["id", "group_key"]), false)]
    fn group_needs_properties_reflects_whether_mask_requests_property_fields(
        #[case] mask_fields: Option<Vec<&str>>,
        #[case] expected: bool,
    ) {
        let read_options = mask_fields.map(read_options_with_mask).flatten();
        assert_eq!(group_needs_properties(&read_options), expected);
    }

    #[test]
    fn needs_properties_with_custom_property_fields_matches_against_those_fields() {
        let custom_fields = &["custom_prop"];
        assert!(!needs_properties(
            &read_options_with_mask(vec!["id"]),
            custom_fields
        ));
        assert!(needs_properties(
            &read_options_with_mask(vec!["custom_prop"]),
            custom_fields
        ));
    }

    // ============================================================
    // apply_person_field_mask
    // ============================================================

    #[test]
    fn apply_person_field_mask_preserves_all_fields_when_mask_is_none() {
        let mut person = populated_person();
        apply_person_field_mask(&mut person, &None);
        let expected = populated_person();
        assert_eq!(person.id, expected.id);
        assert_eq!(person.uuid, expected.uuid);
        assert_eq!(person.team_id, expected.team_id);
        assert_eq!(person.properties, expected.properties);
        assert_eq!(
            person.properties_last_updated_at,
            expected.properties_last_updated_at
        );
        assert_eq!(
            person.properties_last_operation,
            expected.properties_last_operation
        );
        assert_eq!(person.created_at, expected.created_at);
        assert_eq!(person.version, expected.version);
        assert_eq!(person.is_identified, expected.is_identified);
        assert_eq!(person.is_user_id, expected.is_user_id);
        assert_eq!(person.last_seen_at, expected.last_seen_at);
    }

    #[test]
    fn apply_person_field_mask_keeps_only_id_when_mask_contains_only_id() {
        let mut person = populated_person();
        let fields = Some(HashSet::from(["id".to_string()]));
        apply_person_field_mask(&mut person, &fields);

        assert_eq!(person.id, 42, "id should be preserved");
        assert!(person.uuid.is_empty(), "uuid should be zeroed");
        assert_eq!(person.team_id, 0, "team_id should be zeroed");
        assert!(person.properties.is_empty(), "properties should be zeroed");
        assert!(
            person.properties_last_updated_at.is_empty(),
            "properties_last_updated_at should be zeroed"
        );
        assert!(
            person.properties_last_operation.is_empty(),
            "properties_last_operation should be zeroed"
        );
        assert_eq!(person.created_at, 0, "created_at should be zeroed");
        assert_eq!(person.version, 0, "version should be zeroed");
        assert!(!person.is_identified, "is_identified should be zeroed");
        assert!(person.is_user_id.is_none(), "is_user_id should be zeroed");
        assert!(
            person.last_seen_at.is_none(),
            "last_seen_at should be zeroed"
        );
    }

    #[rstest]
    #[case::id("id", |p: &Person| p.id == 42)]
    #[case::uuid("uuid", |p: &Person| p.uuid == "some-uuid")]
    #[case::team_id("team_id", |p: &Person| p.team_id == 7)]
    #[case::properties("properties", |p: &Person| !p.properties.is_empty())]
    #[case::properties_last_updated_at("properties_last_updated_at", |p: &Person| !p.properties_last_updated_at.is_empty())]
    #[case::properties_last_operation("properties_last_operation", |p: &Person| !p.properties_last_operation.is_empty())]
    #[case::created_at("created_at", |p: &Person| p.created_at == 1000)]
    #[case::version("version", |p: &Person| p.version == 3)]
    #[case::is_identified("is_identified", |p: &Person| p.is_identified)]
    #[case::is_user_id("is_user_id", |p: &Person| p.is_user_id.is_some())]
    #[case::last_seen_at("last_seen_at", |p: &Person| p.last_seen_at.is_some())]
    fn apply_person_field_mask_preserves_single_requested_field(
        #[case] field: &str,
        #[case] check: impl Fn(&Person) -> bool,
    ) {
        let mut person = populated_person();
        let fields = Some(HashSet::from([field.to_string()]));
        apply_person_field_mask(&mut person, &fields);
        assert!(check(&person), "field '{field}' should be preserved");
    }

    #[test]
    fn apply_person_field_mask_with_subset_preserves_only_requested_fields() {
        let mut person = populated_person();
        let fields = Some(HashSet::from([
            "id".to_string(),
            "is_identified".to_string(),
        ]));
        apply_person_field_mask(&mut person, &fields);

        assert_eq!(person.id, 42, "id should be preserved");
        assert!(person.is_identified, "is_identified should be preserved");
        assert!(person.uuid.is_empty(), "uuid should be zeroed");
        assert_eq!(person.team_id, 0, "team_id should be zeroed");
        assert_eq!(person.version, 0, "version should be zeroed");
    }

    #[test]
    fn apply_person_field_mask_ignores_unknown_field_names() {
        let mut person = populated_person();
        let fields = Some(HashSet::from([
            "id".to_string(),
            "totally_unknown_field".to_string(),
        ]));
        apply_person_field_mask(&mut person, &fields);

        assert_eq!(person.id, 42, "id should be preserved");
        assert!(
            person.uuid.is_empty(),
            "uuid should be zeroed by the real mask logic"
        );
    }

    // ============================================================
    // apply_group_field_mask
    // ============================================================

    #[test]
    fn apply_group_field_mask_preserves_all_fields_when_mask_is_none() {
        let mut group = populated_group();
        apply_group_field_mask(&mut group, &None);
        let expected = populated_group();
        assert_eq!(group.id, expected.id);
        assert_eq!(group.team_id, expected.team_id);
        assert_eq!(group.group_type_index, expected.group_type_index);
        assert_eq!(group.group_key, expected.group_key);
        assert_eq!(group.group_properties, expected.group_properties);
        assert_eq!(
            group.properties_last_updated_at,
            expected.properties_last_updated_at
        );
        assert_eq!(
            group.properties_last_operation,
            expected.properties_last_operation
        );
        assert_eq!(group.created_at, expected.created_at);
        assert_eq!(group.version, expected.version);
    }

    #[test]
    fn apply_group_field_mask_keeps_only_id_when_mask_contains_only_id() {
        let mut group = populated_group();
        let fields = Some(HashSet::from(["id".to_string()]));
        apply_group_field_mask(&mut group, &fields);

        assert_eq!(group.id, 10, "id should be preserved");
        assert_eq!(group.team_id, 0, "team_id should be zeroed");
        assert_eq!(
            group.group_type_index, 0,
            "group_type_index should be zeroed"
        );
        assert!(group.group_key.is_empty(), "group_key should be zeroed");
        assert!(
            group.group_properties.is_empty(),
            "group_properties should be zeroed"
        );
        assert!(
            group.properties_last_updated_at.is_empty(),
            "properties_last_updated_at should be zeroed"
        );
        assert!(
            group.properties_last_operation.is_empty(),
            "properties_last_operation should be zeroed"
        );
        assert_eq!(group.created_at, 0, "created_at should be zeroed");
        assert_eq!(group.version, 0, "version should be zeroed");
    }

    #[rstest]
    #[case::id("id", |g: &Group| g.id == 10)]
    #[case::team_id("team_id", |g: &Group| g.team_id == 5)]
    #[case::group_type_index("group_type_index", |g: &Group| g.group_type_index == 2)]
    #[case::group_key("group_key", |g: &Group| g.group_key == "acme")]
    #[case::group_properties("group_properties", |g: &Group| !g.group_properties.is_empty())]
    #[case::properties_last_updated_at("properties_last_updated_at", |g: &Group| !g.properties_last_updated_at.is_empty())]
    #[case::properties_last_operation("properties_last_operation", |g: &Group| !g.properties_last_operation.is_empty())]
    #[case::created_at("created_at", |g: &Group| g.created_at == 2000)]
    #[case::version("version", |g: &Group| g.version == 1)]
    fn apply_group_field_mask_preserves_single_requested_field(
        #[case] field: &str,
        #[case] check: impl Fn(&Group) -> bool,
    ) {
        let mut group = populated_group();
        let fields = Some(HashSet::from([field.to_string()]));
        apply_group_field_mask(&mut group, &fields);
        assert!(check(&group), "field '{field}' should be preserved");
    }

    #[test]
    fn apply_group_field_mask_with_subset_preserves_only_requested_fields() {
        let mut group = populated_group();
        let fields = Some(HashSet::from([
            "group_key".to_string(),
            "group_type_index".to_string(),
        ]));
        apply_group_field_mask(&mut group, &fields);

        assert_eq!(group.group_key, "acme", "group_key should be preserved");
        assert_eq!(
            group.group_type_index, 2,
            "group_type_index should be preserved"
        );
        assert_eq!(group.id, 0, "id should be zeroed");
        assert_eq!(group.team_id, 0, "team_id should be zeroed");
        assert!(
            group.group_properties.is_empty(),
            "group_properties should be zeroed"
        );
    }

    #[test]
    fn apply_group_field_mask_ignores_unknown_field_names() {
        let mut group = populated_group();
        let fields = Some(HashSet::from([
            "group_key".to_string(),
            "totally_unknown_field".to_string(),
        ]));
        apply_group_field_mask(&mut group, &fields);

        assert_eq!(group.group_key, "acme", "group_key should be preserved");
        assert_eq!(
            group.id, 0,
            "id should be zeroed by the real mask logic"
        );
    }
}
